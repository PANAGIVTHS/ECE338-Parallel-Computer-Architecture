`include "constants.vh"

/*
 ! Reset HAS to be held for at least pipelines * clock cycles to ensure all pipeline registers are cleared and the processor starts in a known state.
 ! We can enforce that somehow later with a reset counter or smthing.
*/

module StreamingProcessor (
    input i_clk,
    input rst,
    input i_dummy_wen,
    output [2:0] o_leds
);

    wire clk;

    clk_wiz_0 clockDivider (
        .clk_in1(i_clk),
        .clk_out1(clk)
    );

    wire idex_branch_taken;
    wire [$clog2(`IMEM_ENTRIES)-1:0] idex_beq_target_idx;
    wire data_hazard;
    reg [4:0] idex_rd;
    wire [31:0] wb_wdata;
    reg [4:0] memwb_rd;

    //! =========================================================================
    //! STAGE 1: INSTRUCTION FETCH
    //! =========================================================================
    (* dont_touch = "true" *) wire [$clog2(`IMEM_ENTRIES)+1:0] program_counter;
    wire [31:0] ifid_instruction;
    wire [$clog2(`IMEM_ENTRIES)-1:0] instr_idx;
    wire [31:0] if_instruction;

    //! Counter returns instruction index not address!
    (* dont_touch = "true" *)
    GUCounter #(.BITS($clog2(`IMEM_ENTRIES))) 
        programCounter (.clk(clk), .i_set_reset({rst, idex_branch_taken}), .i_count_enable(!data_hazard), .i_count_set(idex_beq_target_idx), .o_count_cur(instr_idx));

    assign program_counter = {instr_idx, 2'b00}; // Shift index to multiply by four

    (* dont_touch = "true" *)
    MemorySinglePort #(.INIT_FILE("program.mem"))
            instructionMemory (.clk(clk),
                                // Port A
                                .i_addr_a(instr_idx),
                                .i_ren_a(1'b1),
                                .i_wen_a(1'b0),
                                .i_data_a(32'b0),
                                .o_out_a(ifid_instruction));

                                // Port B
                                // .i_addr_b(10'b0),
                                // .i_ren_b(1'b0),
                                // .i_wen_b(1'b0),
                                // .i_data_b(32'b0));

    //* =========================================================================
    //* PIPELINE REGISTER 1: INSTRUCTION FETCH -> INSTRUCTION DECODE
    //* =========================================================================
    reg [$clog2(`IMEM_ENTRIES)+1:0] ifid_program_counter;

    always @(posedge clk) begin
        if (!rst) begin
            ifid_program_counter <= `INITIAL_PC;
        end else if (!data_hazard) begin
            ifid_program_counter <= program_counter;
        end
    end

    //! =========================================================================
    //! STAGE 2: INSTRUCTION DECODE
    //! =========================================================================
    wire [6:0] id_imm_31_25, id_opcode;
    wire [11:0] id_imm_31_20;
    wire [1:0] id_aluop, id_instr_type;
    wire [4:0] id_rs1, id_rs2, id_rd;
    wire [4:0] id_mux_rs1, id_mux_rs2;
    wire id_is_mul;

    wire id_wen = !({`INSTR_TYPE_S == id_instr_type && `OP_SW == id_opcode} || {`INSTR_TYPE_S == id_instr_type && `OP_BEQ == id_opcode} || (id_rd == 5'b0));

    (* dont_touch = "true" *)
    Decoder decoder (
        .i_instr(ifid_instruction),
        .o_rs1(id_rs1), 
        .o_rs2(id_rs2),
        .o_rd(id_rd),
        .o_imm_31_25(id_imm_31_25),
        .o_imm_31_20(id_imm_31_20),
        .o_aluop(id_aluop),
        .o_instr_type(id_instr_type),
        .opcode(id_opcode)
    );

    assign id_is_mul = (id_opcode == `OP_R_TYPE);
    assign id_mux_rs1 = data_hazard ? 5'b0 : id_rs1;
    assign id_mux_rs2 = data_hazard ? 5'b0 : id_rs2;


    //* =========================================================================
    //* PIPELINE REGISTER 2: INSTRUCTION DECODE -> EXECUTE
    //* =========================================================================
    reg [4:0] idex_rs1, idex_rs2;
    reg [11:0] idex_imm_31_20;
    reg [1:0] idex_aluop, idex_instr_type;
    reg [6:0] idex_opcode, idex_imm_31_25;
    reg [$clog2(`IMEM_ENTRIES)+1:0] idex_program_counter;
    reg idex_wen;

    always @(posedge clk) begin
        if (!rst) begin
            idex_rs1 <= 5'b0;
            idex_rs2 <= 5'b0;
            idex_rd <= 5'b0;
            idex_imm_31_20 <= 12'b0;
            idex_aluop <= 2'b0;
            idex_instr_type <= 2'b0;
            idex_opcode <= 7'b0;
            idex_imm_31_25 <= 7'b0;
            idex_program_counter <= `INITIAL_PC;
            idex_wen <= 1'b0;
        end else if (data_hazard) begin
            //! Mux for NOP insertion on hazard
            idex_rs1 <= 5'b0;
            idex_rs2 <= 5'b0;
            idex_rd <= 5'b0;
            idex_imm_31_20 <= 12'b0;
            idex_aluop <= `ALU_ADD;
            idex_instr_type <= `INSTR_TYPE_R;
            idex_opcode <= 7'b0;
            idex_imm_31_25 <= 7'b0;
            idex_program_counter <= ifid_program_counter;
            idex_wen <= 1'b0;
        end else begin
            idex_rs1 <= id_rs1;
            idex_rs2 <= id_rs2;
            idex_rd <= id_rd;
            idex_imm_31_20 <= id_imm_31_20;
            idex_imm_31_25 <= id_imm_31_25;
            idex_aluop <= id_aluop;
            idex_instr_type <= id_instr_type;
            idex_opcode <= id_opcode;
            idex_program_counter <= ifid_program_counter;
            idex_wen <= id_wen;
        end
    end

    //! =========================================================================
    //! STAGE 3: EXECUTE
    //! =========================================================================
    wire [31:0] ex_alu_out, ex_alu_mul_out;
    wire ex_zero, ex_is_beq;
    wire [31:0] ex_beq_offset;
    wire [31:0] ex_imm_i_type, ex_imm_s_type;
    wire [31:0] ex_reg_a, ex_reg_b;
    wire [31:0] forwarded_rs2;
    wire [31:0] ex_actual_alu_in_a;
    wire [31:0] ex_actual_alu_in_b;
    wire [1:0] forward_alu_a, forward_alu_b;
    wire ex_is_mul;
    
    reg memwb_wen;

    assign ex_is_mul = (idex_opcode == `OP_R_TYPE) && (idex_imm_31_25 == `FUNCT7_MULDIV);
    assign ex_imm_i_type = {{20{idex_imm_31_20[11]}}, idex_imm_31_20};
    assign ex_imm_s_type = {{20{idex_imm_31_25[6]}}, idex_imm_31_25, idex_rd};

    (* dont_touch = "true" *)
    Regfile regfile (
        .clk(clk), .rst(rst), .i_wen(memwb_wen), .i_wdata(wb_wdata), 
        .i_addr_a(id_mux_rs1), .i_addr_b(id_mux_rs2), .i_waddr(memwb_rd), 
        .o_reg_a(ex_reg_a), .o_reg_b(ex_reg_b)
    );

    assign forwarded_rs2 = (forward_alu_b == `EXALU_MEMALU_DEP) ? exmem_alu_out :
                        (forward_alu_b == `MEMWB_EXALU_DEP)  ? wb_wdata : 
                        ex_reg_b;

    //? --- Forwarding Multiplexer A ---
    assign ex_actual_alu_in_a = (forward_alu_a == `EXALU_MEMALU_DEP) ? exmem_alu_out :
                                (forward_alu_a == `MEMWB_EXALU_DEP)  ? wb_wdata : 
                                ex_reg_a;
    
    //? --- Forwarding Multiplexer B ---
    assign ex_actual_alu_in_b = (idex_opcode == `OP_LW || idex_instr_type == `INSTR_TYPE_I) ? ex_imm_i_type :
                                (idex_opcode == `OP_SW) ? ex_imm_s_type : 
                                forwarded_rs2;

    (* dont_touch = "true" *)
    ALU alu (
        .clk(clk),
        .i_operand_a(ex_actual_alu_in_a), 
        .i_operand_b(ex_actual_alu_in_b), 
        .i_alu_op(idex_aluop), 
        .i_mul_valid(1'b0), //! Temporarily zero.
        .o_alu_out(ex_alu_out), 
        .o_alu_zero(ex_zero),
        .o_mul_out(ex_alu_mul_out)
    );


    //? =========================
    //? MUL PIPELINE TRACKING
    //? =========================
    reg [4:0] mul1_rd, mul2_rd, mul3_rd;
    reg mul1_valid, mul2_valid, mul3_valid;

    always @(posedge clk) begin
        if (!rst) begin
            mul1_rd <= 0; mul2_rd <= 0; mul3_rd <= 0;
            mul1_valid <= 0; mul2_valid <= 0; mul3_valid <= 0;
        end else begin
            mul1_rd <= idex_rd;
            mul2_rd <= mul1_rd;
            mul3_rd <= mul2_rd;
            mul1_valid <= ex_is_mul && !(id_wen && (id_rd == idex_rd));
            mul2_valid <= mul1_valid && !(id_wen && (id_rd == mul1_rd));
            mul3_valid <= mul2_valid && !(id_wen && (id_rd == mul2_rd));
        end
    end

    assign ex_is_beq = (idex_opcode == `OP_BEQ);
    assign idex_branch_taken = ex_is_beq && ex_zero;

    (* dont_touch = "true" *)
    HazardUnit hazardUnit (
        .i_id_rs1(id_rs1),
        .i_id_rs2(id_rs2),
        .i_ex_wen(idex_wen),
        .i_idex_rd(idex_rd),
        .i_is_load(idex_opcode == `OP_LW && idex_instr_type == `INSTR_TYPE_I),
        .i_mul1_valid(mul1_valid),
        .i_id_instr_type(id_instr_type),
        .i_mul1_rd(mul1_rd),
        .i_mul2_valid(mul2_valid),
        .i_mul2_rd(mul2_rd),
        .i_branch_taken(idex_branch_taken),
        .o_data_hazard(data_hazard)
    );

    assign ex_beq_offset = {{20{idex_imm_31_25[6]}}, idex_rd[0], idex_imm_31_25[5:0], idex_rd[4:1], 1'b0};
    assign idex_beq_target_idx = idex_program_counter[$clog2(`IMEM_ENTRIES)+1:2] + ex_beq_offset[31:2];

    //* =========================================================================
    //* PIPELINE REGISTER 3: EXECUTE -> MEMORY
    //* =========================================================================
    reg [31:0] exmem_alu_out, exmem_alu_mul_out, exmem_reg_b;
    reg [31:0] exmem_program_counter;
    reg [6:0] exmem_opcode;
    reg [1:0] exmem_instr_type;
    reg [4:0] exmem_rd;
    reg exmem_mul3_valid, exmem_wen;

    always @(posedge clk) begin
        if (!rst) begin
            exmem_alu_out <= 32'b0;
            exmem_reg_b <= 32'b0;
            exmem_rd <= 5'b0;
            exmem_opcode <= 7'b0;
            exmem_wen <= 1'b0;
            exmem_mul3_valid <= 1'b0;
            exmem_alu_mul_out <= 32'b0;
            exmem_program_counter <= `INITIAL_PC;
        end else begin
            exmem_alu_out <= ex_alu_out;
            exmem_reg_b <= forwarded_rs2;
            exmem_mul3_valid <= mul3_valid;
            exmem_rd <= mul3_valid ? mul3_rd : idex_rd;
            exmem_opcode <= idex_opcode;
            exmem_wen <= idex_wen;
            exmem_alu_mul_out <= ex_alu_mul_out;
            exmem_program_counter <= idex_program_counter;
        end
    end

    //! =========================================================================
    //! STAGE 4: MEMORY
    //! =========================================================================
    (* dont_touch = "true" *) wire mem_is_load, mem_is_store;
    (* dont_touch = "true" *) wire [31:0] mem_dmem_out;

    assign mem_is_load = (exmem_opcode == `OP_LW);
    assign mem_is_store = (exmem_opcode == `OP_SW);

    (* dont_touch = "true" *)
    MemoryDualPort dataMemory (.clk(clk),
                       // Port A
                       .i_addr_a(exmem_alu_out[11:2]),
                       .i_ren_a(mem_is_load),
                       .i_wen_a(mem_is_store),
                       .i_data_a(exmem_reg_b),
                       .o_out_a(mem_dmem_out),

                       // Port B
                       .i_addr_b(10'b0),
                       .i_ren_b(1'b0),
                       .i_wen_b(1'b0),
                       .i_data_b(32'b0));

    //! =========================================================================
    //! PIPELINE REGISTER 4: MEMORY -> WRITE BACK
    //! =========================================================================
    reg memwb_is_mul, memwb_is_load;
    reg [31:0] memwb_alu_out, memwb_alu_mul_out;
    reg [$clog2(`IMEM_ENTRIES)+1:0] memwb_program_counter;

    always @(posedge clk) begin
        if (!rst) begin
            memwb_rd <= 5'b0;
            memwb_is_mul <= 1'b0;
            memwb_is_load <= 1'b0;
            memwb_alu_out <= 32'b0;
            memwb_alu_mul_out <= 32'b0;
            memwb_wen <= 1'b0;
            memwb_program_counter <= `INITIAL_PC;
        end else begin
            memwb_rd <= exmem_rd;
            memwb_is_mul <= exmem_mul3_valid;
            memwb_is_load <= mem_is_load;
            memwb_alu_out <= exmem_alu_out;
            memwb_alu_mul_out <= exmem_alu_mul_out;
            memwb_wen <= exmem_wen;
            memwb_program_counter <= exmem_program_counter;
        end
    end

    //! =========================================================================
    //! STAGE 5: WRITE BACK
    //! =========================================================================

    assign wb_wdata = memwb_is_mul ? memwb_alu_mul_out : (memwb_is_load ? mem_dmem_out : memwb_alu_out);

    assign o_leds[0] = i_dummy_wen;
    assign o_leds[1] = ^memwb_alu_out;
    assign o_leds[2] = ^exmem_reg_b;

    //& ===============
    //& FORWARDING
    //& ===============
    (* dont_touch = "true" *)
    ForwardingUnit forwardingUnit (
        .i_idex_rs1(idex_rs1),
        .i_idex_rs2(idex_rs2),
        .i_exmem_rd(exmem_rd),
        .i_exmem_wen(exmem_wen),
        .i_idex_instr_type(idex_instr_type),
        .i_memwb_rd(memwb_rd),
        .i_memwb_wen(memwb_wen),
        .o_forward_alu_a(forward_alu_a),
        .o_forward_alu_b(forward_alu_b)
    );
endmodule