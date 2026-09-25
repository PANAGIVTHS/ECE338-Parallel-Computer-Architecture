`include "constants.vh"

module StreamingProcessor #(
    parameter CORE_ID = 0
)(
    input clk,
    input rst,

    //! Regfile Read Addresses
    input [4:0] i_id_mux_rs1,
    input [4:0] i_id_mux_rs2,

    //! Pipeline Register: IDEX -> EX
    input [4:0] i_idex_rs1,
    input [4:0] i_idex_rs2,
    input [4:0] i_idex_rd,
    input [19:0] i_idex_imm_31_12,
    input [11:0] i_idex_imm_31_20,
    input [6:0] i_idex_imm_31_25,
    input [2:0] i_idex_funct3,
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
    input  [31:0] i_mem_rdata,

    //! New Memory Queue / Arbiter Interface
    input i_mem_grant,
    input i_mem_rvalid,
    input i_global_stall,
    output o_core_complete
);

    //! =========================================================================
    //! STAGE 3: EXECUTE
    //! =========================================================================
    wire [31:0] ex_alu_out;
    wire ex_zero, ex_is_branch, ex_is_jal, ex_is_jalr;
    wire ex_branch_condition_met;
    wire [31:0] ex_beq_offset, ex_jal_offset, ex_jalr_target_addr;
    wire [31:0] ex_branch_operand_a, ex_branch_operand_b, ex_branch_target_addr;
    wire [31:0] ex_imm_i_type, ex_imm_s_type, ex_imm_u_type;
    wire [31:0] ex_reg_a, ex_reg_b;
    wire [31:0] forwarded_rs2;
    wire [31:0] ex_actual_alu_in_a;
    reg [31:0] ex_actual_alu_in_b;
    wire [1:0] forward_alu_a, forward_alu_b;
    wire ex_is_mul, mul_not_ready;
    reg [4:0] memwb_rd;
    reg memwb_wen;
    wire [31:0] wb_wdata;

    assign ex_is_mul = (i_idex_opcode == `OP_R_TYPE) && (i_idex_imm_31_25 == `FUNCT7_MULDIV);
    assign ex_imm_i_type = {{20{i_idex_imm_31_20[11]}}, i_idex_imm_31_20};
    assign ex_imm_s_type = {{20{i_idex_imm_31_25[6]}}, i_idex_imm_31_25, i_idex_rd};
    assign ex_imm_u_type = {i_idex_imm_31_12, 12'b0};

    (* dont_touch = `DEBUG *)
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
    assign ex_actual_alu_in_a = (i_idex_opcode == `OP_JAL) ? i_idex_program_counter :
                                (forward_alu_a == `EXALU_MEMALU_DEP) ? exmem_alu_out :
                                (forward_alu_a == `MEMWB_EXALU_DEP)  ? wb_wdata :
                                 ex_reg_a;

    //? --- Final ALU Input B ---
    always @(*) begin
        if (i_idex_opcode == `OP_JAL) begin
            ex_actual_alu_in_b = 32'd4;
        end else if (i_idex_opcode == `OP_LW || i_idex_instr_type == `INSTR_TYPE_I) begin
            ex_actual_alu_in_b = ex_imm_i_type;
        end else if (i_idex_opcode == `OP_SW) begin
            ex_actual_alu_in_b = ex_imm_s_type;
        end else if (i_idex_instr_type == `INSTR_TYPE_U) begin
            ex_actual_alu_in_b = ex_imm_u_type;
        end else begin
            ex_actual_alu_in_b = forwarded_rs2;
        end
    end

    (* dont_touch = `DEBUG *)
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
    assign mul_not_ready = (ex_is_mul || mul1_valid || mul2_valid) && !mul3_valid;

    assign ex_is_branch = (i_idex_opcode == `OP_BEQ);
    assign ex_is_jal = (i_idex_opcode == `OP_JAL);
    assign ex_is_jalr = (i_idex_opcode == `OP_JALR);
    assign ex_branch_condition_met =
        (i_idex_funct3 == `FUNCT3_BEQ) ? (ex_zero) :
        (i_idex_funct3 == `FUNCT3_BNE) ? (!ex_zero) :
        (i_idex_funct3 == `FUNCT3_BLT) ? (ex_alu_out) :
        (i_idex_funct3 == `FUNCT3_BGE) ? (!ex_alu_out) :
        (i_idex_funct3 == `FUNCT3_BLTU) ? (ex_alu_out) :
        (i_idex_funct3 == `FUNCT3_BGEU) ? (!ex_alu_out) :
        1'b0;
    assign o_ex_branch_taken = (ex_is_branch && ex_branch_condition_met) || ex_is_jal || ex_is_jalr;

    assign ex_beq_offset = {{20{i_idex_imm_31_25[6]}}, i_idex_rd[0], i_idex_imm_31_25[5:0], i_idex_rd[4:1], 1'b0};
    assign ex_jal_offset = {{12{i_idex_imm_31_12[19]}}, i_idex_imm_31_12[7:0], i_idex_imm_31_12[8], i_idex_imm_31_12[18:9], 1'b0};
    assign ex_jalr_target_addr = ex_alu_out & 32'hFFFF_FFFE;

    assign ex_branch_operand_a = ex_is_jalr ? i_idex_program_counter : i_idex_program_counter[$clog2(`IMEM_ENTRIES)+1:2];
    assign ex_branch_operand_b = ex_is_jalr ? 32'd4 : (ex_is_jal ? ex_jal_offset[31:2] : ex_beq_offset[31:2]);
    assign ex_branch_target_addr = ex_branch_operand_a + ex_branch_operand_b;
    assign o_ex_beq_target_idx = ex_is_jalr
        ? ex_jalr_target_addr[$clog2(`IMEM_ENTRIES)+1:2]
        : ex_branch_target_addr;

    //* =========================================================================
    //* PIPELINE REGISTER 3: EXECUTE -> MEMORY
    //* =========================================================================
    reg [31:0] exmem_alu_out, exmem_reg_b;
    reg [31:0] exmem_program_counter;
    reg [6:0] exmem_opcode;
    reg [1:0] exmem_instr_type;
    reg [4:0] exmem_rd;
    reg exmem_mul3_valid, exmem_wen, exmem_core_complete;

    always @(posedge clk) begin
        if (!rst) begin
            exmem_alu_out <= 32'b0;
            exmem_reg_b <= 32'b0;
            exmem_rd <= 5'b0;
            exmem_opcode <= 7'b0;
            exmem_wen <= 1'b0;
            exmem_mul3_valid <= 1'b0;
            exmem_core_complete <= 1'b0;
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
            exmem_core_complete <= 1'b0;
            exmem_program_counter <= `INITIAL_PC;
        end else begin
            exmem_alu_out <= (ex_is_jalr) ? ex_branch_target_addr : ex_alu_out;
            exmem_reg_b <= forwarded_rs2;
            exmem_mul3_valid <= mul3_valid;
            exmem_rd <= mul3_valid ? mul3_rd : i_idex_rd;
            exmem_opcode <= mul3_valid ? `OP_R_TYPE : i_idex_opcode;
            exmem_wen <= mul3_valid ? (mul3_rd != 5'b0) : (i_idex_wen && i_idex_rd != 5'b0);
            exmem_core_complete <= ex_is_jalr &&
                                   (i_idex_rd == 5'b0) &&
                                   (i_idex_rs1 == 5'd1) &&
                                   (ex_imm_i_type == 32'b0);
            exmem_program_counter <= mul3_valid ? mul3_program_counter : i_idex_program_counter;
        end
    end

    //! =========================================================================
    //! STAGE 4: MEMORY
    //! =========================================================================
    wire mem_is_load, mem_is_store;
    assign mem_is_load = (exmem_opcode == `OP_LW);
    assign mem_is_store = (exmem_opcode == `OP_SW);

    assign o_mem_addr = exmem_alu_out[$clog2(`DMEM_ENTRIES)+1 : 2];
    assign o_mem_ren = mem_is_load | mem_is_store;
    assign o_mem_wen = mem_is_store;
    assign o_mem_wdata = exmem_reg_b;
    assign o_core_complete = exmem_core_complete;

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
            memwb_is_load <= mem_is_load;
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
    (* dont_touch = `DEBUG *)
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