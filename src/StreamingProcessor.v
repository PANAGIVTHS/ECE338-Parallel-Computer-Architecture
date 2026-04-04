`include "constants.vh"

module StreamingProcessor (
    input clk,
    input rst,
    output [2:0] o_leds
);

    //! =========================================================================
    //! STAGE 1: FETCH & DECODE
    //! =========================================================================
    wire [31:0] fd_instruction, fd_program_counter;
    (* dont_touch = "true" *) wire [31:0] fd_o_fetched_instr;
    wire [29:0] fd_instr_idx;
    wire [6:0] fd_imm_31_25, fd_opcode;
    wire [11:0] fd_imm_31_20;
    wire [1:0] fd_aluop, fd_instr_type;
    wire [4:0] fd_rs1, fd_rs2, fd_rd;
    wire fd_is_beq;
    
    // Counter returns instruction index not address!
    GUCounter #(.BITS(30)) 
        program_counter_inst (.clk(clk), .i_set_reset({rst, ra_branch_taken}), .i_count_enable(!ra_branch_taken && !raw_mul_hazard), .i_count_set(ra_beq_target_idx), .o_count_cur(fd_instr_idx));
    
    assign fd_program_counter = {fd_instr_idx, 2'b00};

    InstrFetch instr_fetch_inst (.clk(clk), .rst(rst), .i_program_counter(fd_program_counter), .o_fetched_instr(fd_o_fetched_instr));
    
    // If program counter is stalled due to a taken branch insert NOP.
    assign fd_instruction = (ra_branch_taken) ? 32'b0 : fd_o_fetched_instr;

    Decoder decoder_inst (.i_instr(fd_instruction), .o_rs1(fd_rs1), .o_rs2(fd_rs2), .o_rd(fd_rd), .o_imm_31_25(fd_imm_31_25), .o_imm_31_20(fd_imm_31_20), .o_aluop(fd_aluop), .o_instr_type(fd_instr_type), .opcode(fd_opcode));

    assign fd_is_beq = fd_opcode == `OP_BEQ;

    //* =========================================================================
    //* PIPELINE REGISTER 1: DECODE -> REG/ALU 
    //* =========================================================================
    reg [4:0] ra_rs1, ra_rs2, ra_rd;
    reg [11:0] ra_imm_31_20;
    reg [1:0] ra_aluop, ra_instr_type;
    reg [6:0] ra_opcode, ra_imm_31_25;
    reg [31:0] ra_program_counter;

    always @(posedge clk or posedge rst) begin
        if (rst) begin
            ra_rs1 <= 5'b0;
            ra_rs2 <= 5'b0;
            ra_rd <= 5'b0;
            ra_imm_31_20 <= 12'b0;
            ra_aluop <= 2'b0;
            ra_instr_type <= 2'b0;
            ra_opcode <= 7'b0;
            ra_imm_31_25 <= 7'b0;
            ra_program_counter <= 32'b0;
        end else begin
            ra_rs1 <= fd_rs1;
            ra_rs2 <= fd_rs2;
            ra_rd <= fd_rd;
            ra_imm_31_20 <= fd_imm_31_20;
            ra_imm_31_25 <= fd_imm_31_25;
            ra_aluop <= fd_aluop;
            ra_instr_type <= fd_instr_type;
            ra_opcode <= fd_opcode;
            ra_program_counter <= fd_program_counter;
        end
    end

    //! =========================================================================
    //! STAGE 2: REGFILE & ALU 
    //! =========================================================================
    wire [31:0] ra_o_reg_a, ra_o_reg_b, ra_alu_in_b, ra_alu_in_a, ra_alu_out;
    wire ra_zero, ra_branch_taken, ra_is_beq;
    wire [31:0] ra_beq_offset;
    wire [29:0] ra_beq_target_idx;

    Regfile regfile_inst (.clk(clk), .rst(rst), .i_wen(wb_wen), .i_wdata(wb_wdata), .i_addr_a(ra_rs1), .i_addr_b(ra_rs2), .i_waddr(mw_rd), .o_reg_a(ra_o_reg_a), .o_reg_b(ra_o_reg_b));

    always @* begin
        if (raw_mul_hazard) begin
            ra_alu_in_b = 32'b0;
        end else if (ra_instr_type == `INSTR_TYPE_I) begin
            ra_alu_in_b = {{20{ra_imm_31_20[11]}}, ra_imm_31_20};
        end else begin
            ra_alu_in_b = ra_o_reg_b;
        end 
    end

    assign ra_alu_in_a = raw_mul_hazard ? 32'b0 : ra_o_reg_a;

    ALU alu_inst (.i_operand_a(ra_alu_in_a), .i_operand_b(ra_alu_in_b), .i_alu_op(ra_aluop), .o_alu_out(ra_alu_out), .o_alu_zero(ra_zero));

    //? =========================
    //? MUL PIPELINE TRACKING
    //? =========================
    reg [4:0] mul1_rd, mul2_rd, mul3_rd;
    reg mul1_valid, mul2_valid, mul3_valid;

    wire ra_is_mul;
    assign ra_is_mul = (ra_aluop == `ALU_MUL);

    always @(posedge clk or posedge rst) begin
        if (rst) begin
            mul1_rd <= 0; mul2_rd <= 0; mul3_rd <= 0;
            mul1_valid <= 0; mul2_valid <= 0; mul3_valid <= 0;
        end else begin
            mul1_rd <= ra_rd;
            mul2_rd <= mul1_rd;
            mul3_rd <= mul2_rd;

            mul1_valid <= ra_is_mul;
            mul2_valid <= mul1_valid;
            mul3_valid <= mul2_valid;

            //! WAW kill WB data is not forwarded to regfile
            if (ra_rd != 0) begin
                if (mul1_valid && (ra_rd == mul1_rd)) mul1_valid <= 0;
                if (mul2_valid && (ra_rd == mul2_rd)) mul2_valid <= 0;
                if (mul3_valid && (ra_rd == mul3_rd)) mul3_valid <= 0;
            end
        end
    end

    //? =========================
    //? MUL HAZARD DETECTION
    //? =========================
    wire raw_mul_hazard;

    assign raw_mul_hazard =
        (mul1_valid && ((ra_rs1 == mul1_rd && ra_rs1 != 0) || (ra_rs2 == mul1_rd && ra_rs2 != 0))) ||
        (mul2_valid && ((ra_rs1 == mul2_rd && ra_rs1 != 0) || (ra_rs2 == mul2_rd && ra_rs2 != 0))) ||
        (mul3_valid && ((ra_rs1 == mul3_rd && ra_rs1 != 0) || (ra_rs2 == mul3_rd && ra_rs2 != 0)));

    assign ra_is_beq = (ra_opcode == `OP_BEQ);
    assign ra_branch_taken = ra_is_beq && ra_zero;

    assign ra_beq_offset = {{20{ra_imm_31_25[6]}}, ra_rd[0], ra_imm_31_25[5:0], ra_rd[4:1], 1'b0};
    assign ra_beq_target_idx = ra_program_counter[31:2] + ra_beq_offset[31:2];

    //* =========================================================================
    //* PIPELINE REGISTER 2: REGFILE & ALU -> LSU
    //* =========================================================================
    reg [31:0] mw_alu_out, mw_reg_b;
    reg [4:0] mw_rd;
    reg [6:0] mw_opcode;
    reg [1:0] mw_instr_type;

    always @(posedge clk or posedge rst) begin
        if (rst) begin
            mw_alu_out <= 32'b0;
            mw_reg_b <= 32'b0;
            mw_rd <= 5'b0;
            mw_opcode <= 7'b0;
            mw_instr_type <= 2'b0;
        end else begin
            mw_alu_out <= ra_alu_out;
            mw_reg_b <= ra_o_reg_b;
            mw_rd <= ra_rd;
            mw_opcode <= ra_opcode;
            mw_instr_type <= ra_instr_type;
        end
    end

    //! =========================================================================
    //! STAGE 3: MEMORY & WB
    //! =========================================================================
    (* dont_touch = "true" *) wire mw_is_load, mw_is_store;
    (* dont_touch = "true" *) wire [31:0] mw_mem_out;
    wire [31:0] wb_wdata;
    wire wb_wen;

    assign mw_is_load = (mw_opcode == `OP_LW);
    assign mw_is_store = (mw_opcode == `OP_SW);

    LoadStoreUnit load_store_unit_inst (.clk(clk), .rst(rst), .i_write_enable(mw_is_store), .i_read_enable(mw_is_load), .i_addr(mw_alu_out), .i_wdata(mw_reg_b), .o_rdata(mw_mem_out));

    assign wb_wdata = mw_is_load ? mw_mem_out : mw_alu_out;
    wire mw_is_mul;
    assign mw_is_mul = (mw_opcode == `OP_MUL);

    assign wb_wen = ((mw_instr_type == `INSTR_TYPE_R) || (mw_instr_type == `INSTR_TYPE_I)) && !(mw_is_mul && !mul3_valid);

    assign o_leds[0] = ^mw_mem_out;
    assign o_leds[1] = ^ra_alu_out;
    assign o_leds[2] = ^mw_reg_b;

endmodule