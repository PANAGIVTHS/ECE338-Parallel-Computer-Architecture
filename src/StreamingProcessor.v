`include "constants.vh"

module StreamingProcessor #(
    parameter CORE_ID = 0
)(
    input i_clk,
    input rst,
    input i_dummy_wen,
    output [2:0] o_leds,

    //! Regfile Read Addresses
    input [4:0] i_id_mux_rs1,
    input [4:0] i_id_mux_rs2,

    //! Pipeline Register: IDEX -> EX
    input [4:0] i_idex_rs1,
    input [4:0] i_idex_rs2,
    input [4:0] i_idex_rd,
    input [11:0] i_idex_imm_31_20,
    input [6:0] i_idex_imm_31_25,
    input [3:0] i_idex_aluop,
    input [1:0] i_idex_instr_type,
    input [6:0] i_idex_opcode,
    input [$clog2(`IMEM_ENTRIES)+1:0] i_idex_program_counter,
    input i_idex_wen,

    //! Hazard and Branch feedback
    output o_ex_branch_taken,
    output [$clog2(`IMEM_ENTRIES)-1:0] o_ex_beq_target_idx,
    output o_mul1_valid,
    output [4:0] o_mul1_rd,
    output o_mul2_valid,
    output [4:0] o_mul2_rd,
    output o_mul3_valid,
    output [4:0] o_mul3_rd,

    //! External Memory Interface
    output [$clog2(`DMEM_ENTRIES)-1:0] o_mem_addr,
    output [31:0] o_mem_wdata,
    output o_mem_ren,
    output o_mem_wen,
    output o_mem_amo,
    input  [31:0] i_mem_rdata,

    //! New Memory Queue / Arbiter Interface
    input i_mem_grant,
    input i_mem_rvalid,
    input i_global_stall,
    output o_core_complete
);
    wire clk = i_clk;

    //! =========================================================================
    //! STAGE 3: EXECUTE
    //! =========================================================================
    wire [31:0] ex_alu_out;
    wire ex_zero, ex_is_beq;
    wire [31:0] ex_beq_offset;
    wire [31:0] ex_imm_i_type, ex_imm_s_type;
    wire [31:0] ex_reg_a, ex_reg_b;
    wire [31:0] forwarded_rs2;
    wire [31:0] ex_actual_alu_in_a;
    wire [31:0] ex_actual_alu_in_b;
    wire [1:0] forward_alu_a, forward_alu_b;
    wire ex_is_mul, mul_not_ready;
    reg [4:0] memwb_rd;
    reg memwb_wen;
    wire [31:0] wb_wdata;

    assign ex_is_mul = (i_idex_opcode == `OP_R_TYPE) && (i_idex_imm_31_25 == `FUNCT7_MULDIV);
    assign ex_imm_i_type = {{20{i_idex_imm_31_20[11]}}, i_idex_imm_31_20};
    assign ex_imm_s_type = {{20{i_idex_imm_31_25[6]}}, i_idex_imm_31_25, i_idex_rd};

    (* dont_touch = "true" *)
    Regfile #(
        .CORE_ID(CORE_ID)
    ) regfile (
        .clk(clk), .rst(rst), .i_wen(memwb_wen), .i_wdata(wb_wdata), 
        .i_addr_a(i_id_mux_rs1), .i_addr_b(i_id_mux_rs2), .i_waddr(memwb_rd), 
        .o_reg_a(ex_reg_a), .o_reg_b(ex_reg_b), .i_global_stall(i_global_stall)
    );

    //? --- Forwarding Multiplexer B ---
    assign forwarded_rs2 = (forward_alu_b == `EXALU_MEMALU_DEP) ? exmem_alu_out :
                           (forward_alu_b == `MEMWB_EXALU_DEP)  ? wb_wdata : 
                            ex_reg_b;

    //? --- Forwarding Multiplexer A ---
    assign ex_actual_alu_in_a = (forward_alu_a == `EXALU_MEMALU_DEP) ? exmem_alu_out :
                                (forward_alu_a == `MEMWB_EXALU_DEP)  ? wb_wdata :
                                 ex_reg_a;

    //? --- Final ALU Input B ---
    assign ex_actual_alu_in_b = (i_idex_opcode == `OP_LW || i_idex_instr_type == `INSTR_TYPE_I) ? ex_imm_i_type :
                                (i_idex_opcode == `OP_SW) ? ex_imm_s_type :
                                (i_idex_opcode == `OP_AMO) ? 32'b0 :
                                 forwarded_rs2;

    (* dont_touch = "true" *)
    ALU alu (
        .clk(clk),
        .rst(rst),
        .i_operand_a(ex_actual_alu_in_a), 
        .i_operand_b(ex_actual_alu_in_b),
        .i_global_stall(i_global_stall),
        .i_alu_op(i_idex_aluop), 
        .i_mul_valid(mul3_valid),
        .o_alu_out(ex_alu_out),
        .o_alu_zero(ex_zero)
    );

    //? =========================
    //? MUL PIPELINE TRACKING
    //? =========================
    reg [31:0] mul1_program_counter, mul2_program_counter, mul3_program_counter;
    reg [4:0] mul1_rd, mul2_rd, mul3_rd;
    reg mul1_valid, mul2_valid, mul3_valid;

    always @(posedge clk) begin
        if (!rst) begin
            mul1_rd <= 0;
            mul2_rd <= 0; mul3_rd <= 0;
            mul1_valid <= 0; mul2_valid <= 0; mul3_valid <= 0;
            mul1_program_counter <= 0;
            mul2_program_counter <= 0; mul3_program_counter <= 0;
        end else if (i_global_stall) begin
            // Retain state during memory stall
        end else begin
            mul1_rd <= (ex_is_mul) ? i_idex_rd : 5'b0;
            mul2_rd <= mul1_rd;
            mul3_rd <= mul2_rd;
            mul1_valid <= ex_is_mul && (i_idex_rd != 5'b0);
            mul2_valid <= mul1_valid;
            mul3_valid <= mul2_valid;
            mul1_program_counter <= i_idex_program_counter;
            mul2_program_counter <= mul1_program_counter;
            mul3_program_counter <= mul2_program_counter;
        end
    end

    //! Output MUL for Hazard Unit
    assign o_mul1_valid = mul1_valid;
    assign o_mul1_rd = mul1_rd;
    assign o_mul2_valid = mul2_valid;
    assign o_mul2_rd = mul2_rd;
    assign o_mul3_valid = mul3_valid;
    assign o_mul3_rd = mul3_rd;

    assign ex_is_beq = (i_idex_opcode == `OP_BEQ);
    assign o_ex_branch_taken = ex_is_beq && ex_zero;

    assign ex_beq_offset = {{20{i_idex_imm_31_25[6]}}, i_idex_rd[0], i_idex_imm_31_25[5:0], i_idex_rd[4:1], 1'b0};
    assign o_ex_beq_target_idx = i_idex_program_counter[$clog2(`IMEM_ENTRIES)+1:2] + ex_beq_offset[31:2];
    assign mul_not_ready = (ex_is_mul || mul1_valid || mul2_valid) && !mul3_valid;

    //* =========================================================================
    //* PIPELINE REGISTER 3: EXECUTE -> MEMORY
    //* =========================================================================
    reg [31:0] exmem_alu_out, exmem_reg_b;
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
            exmem_program_counter <= `INITIAL_PC;
        end else if (i_global_stall) begin
            // Retain state during memory stall
        end else if (mul_not_ready) begin
            exmem_alu_out <= 32'b0;
            exmem_reg_b <= 32'b0;
            exmem_rd <= 5'b0;
            exmem_opcode <= 7'b0;
            exmem_wen <= 1'b0;
            exmem_mul3_valid <= 1'b0;
            exmem_program_counter <= `INITIAL_PC;
        end else begin
            exmem_alu_out <= ex_alu_out;
            exmem_reg_b <= forwarded_rs2;
            exmem_mul3_valid <= mul3_valid;
            exmem_rd <= mul3_valid ? mul3_rd : i_idex_rd;
            exmem_opcode <= mul3_valid ? `OP_R_TYPE : i_idex_opcode;
            exmem_wen <= mul3_valid ? (mul3_rd != 5'b0) : (i_idex_wen && i_idex_rd != 5'b0);
            exmem_program_counter <= mul3_valid ? mul3_program_counter : i_idex_program_counter;
        end
    end

    //! =========================================================================
    //! STAGE 4: MEMORY
    //! =========================================================================
    wire mem_is_load, mem_is_store;
    assign mem_is_load = (exmem_opcode == `OP_LW);
    assign mem_is_store = (exmem_opcode == `OP_SW);
    assign mem_is_amo = (exmem_opcode == `OP_AMO);

    assign o_mem_addr = exmem_alu_out[$clog2(`DMEM_ENTRIES)+1 : 2];
    assign o_mem_ren = mem_is_load | mem_is_store | mem_is_amo;
    assign o_mem_wen = mem_is_store;
    assign o_mem_wdata = exmem_reg_b;
    assign o_mem_amo = mem_is_amo;
    assign o_core_complete = (exmem_opcode == `OP_JALR && exmem_rd == 5'b0);

    //! =========================================================================
    //! PIPELINE REGISTER 4: MEMORY -> WRITE BACK
    //! =========================================================================
    reg memwb_is_mul, memwb_is_load;
    reg [31:0] memwb_alu_out;
    reg [$clog2(`IMEM_ENTRIES)+1:0] memwb_program_counter;

    always @(posedge clk) begin
        if (!rst) begin
            memwb_rd <= 5'b0;
            memwb_is_mul <= 1'b0;
            memwb_is_load <= 1'b0;
            memwb_alu_out <= 32'b0;
            memwb_wen <= 1'b0;
            memwb_program_counter <= `INITIAL_PC;
        end else if (i_global_stall) begin
            // Retain state during memory stall
        end else begin
            memwb_rd <= exmem_rd;
            memwb_is_mul <= exmem_mul3_valid;
            memwb_is_load <= mem_is_load | mem_is_amo;
            memwb_alu_out <= exmem_alu_out;
            memwb_wen <= exmem_wen;
            memwb_program_counter <= exmem_program_counter;
        end
    end

    //! =========================================================================
    //! STAGE 5: WRITE BACK
    //! =========================================================================
    reg [31:0] safe_wb_rdata;
    reg safe_wb_valid;

    always @(posedge clk) begin
        if (!rst) begin
            safe_wb_rdata <= 32'b0;
            safe_wb_valid <= 1'b0;
        end else if (!i_global_stall) begin
            //! Pipeline is moving normally. Clear the vault for the next instruction.
            safe_wb_valid <= 1'b0;
        end else if (memwb_is_load && !safe_wb_valid) begin
            //! FIX: We are stalled, and we are a load. Latch the memory data immediately 
            //! before a subsequent load wins the crossbar and overwrites the shared bus.
            safe_wb_rdata <= i_mem_rdata;
            safe_wb_valid <= 1'b1;
        end
    end

    assign wb_wdata = memwb_is_load ? (safe_wb_valid ? safe_wb_rdata : i_mem_rdata) : memwb_alu_out;

    //& ===============
    //& FORWARDING
    //& ===============
    (* dont_touch = "true" *)
    ForwardingUnit forwardingUnit (
        .i_idex_rs1(i_idex_rs1),
        .i_idex_rs2(i_idex_rs2),
        .i_exmem_rd(exmem_rd),
        .i_exmem_wen(exmem_wen),
        .i_idex_instr_type(i_idex_instr_type),
        .i_memwb_rd(memwb_rd),
        .i_memwb_wen(memwb_wen),
        .o_forward_alu_a(forward_alu_a),
        .o_forward_alu_b(forward_alu_b)
    );

endmodule