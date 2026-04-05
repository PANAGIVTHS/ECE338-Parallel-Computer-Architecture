`include "constants.vh"

module StreamingProcessor (
    input clk,
    input rst,
    output [2:0] o_leds
);

    wire ra_branch_taken;
    wire [29:0] ra_beq_target_idx;
    wire data_hazard;
    reg [4:0] ra_rd;
    wire wb_wen;
    wire [31:0] wb_wdata;
    reg [4:0] mw_rd;

    //! =========================================================================
    //! STAGE 1: INSTRUCTION FETCH
    //! =========================================================================
    (* dont_touch = "true" *) wire [31:0] program_counter;
    wire [29:0] instr_idx;
    reg [31:0] if_program_counter;

    //! Counter returns instruction index not address!
    GUCounter #(.BITS(30)) 
        program_counter_inst (.clk(clk), .i_set_reset({rst, ra_branch_taken}), .i_count_enable(!data_hazard), .i_count_set(ra_beq_target_idx), .o_count_cur(instr_idx));

    assign program_counter = {instr_idx, 2'b00};

    //* =========================================================================
    //* PIPELINE REGISTER 1: INSTRUCTION FETCH -> DECODE
    //* =========================================================================
    always @(posedge clk) begin
        if (!rst) begin
            if_program_counter <= 32'b0;
        end else begin
            if_program_counter <= program_counter;
        end
    end

    //! =========================================================================
    //! STAGE 2: DECODE
    //! =========================================================================
    wire [31:0] fd_instruction;
    wire [6:0] fd_imm_31_25, fd_opcode;
    wire [11:0] fd_imm_31_20;
    wire [1:0] fd_aluop, fd_instr_type;
    wire [4:0] fd_rs1, fd_rs2, fd_rd;
    wire [4:0] mux_fd_rs1, mux_fd_rs2;
    wire fd_is_mul;

    //! Generate write-enable for WAW tracking
    wire fd_wen = ((fd_instr_type == `INSTR_TYPE_R) || (fd_instr_type == `INSTR_TYPE_I) || fd_is_mul) && (fd_rd != 5'b0);

    Memory instructionMemory (.clk(clk), .rst(rst), .i_read_addr(if_program_counter[11:2]), .i_read_enable(1'b1), .i_write_addr(10'b0),
                              .i_write_enable(1'b0), .i_write_data(32'b0), .o_out(fd_instruction));

    Decoder decoder_inst (
        .i_instr(fd_instruction),
        .o_rs1(fd_rs1), 
        .o_rs2(fd_rs2),
        .o_rd(fd_rd),
        .o_imm_31_25(fd_imm_31_25),
        .o_imm_31_20(fd_imm_31_20),
        .o_aluop(fd_aluop),
        .o_instr_type(fd_instr_type),
        .opcode(fd_opcode)
    );

    assign fd_is_mul = (fd_opcode == `OP_R_TYPE);
    assign mux_fd_rs1 = data_hazard ? 5'b0 : fd_rs1;
    assign mux_fd_rs2 = data_hazard ? 5'b0 : fd_rs2;

    //* =========================================================================
    //* PIPELINE REGISTER 2: DECODE -> REG/ALU 
    //* =========================================================================
    reg [4:0] ra_rs1, ra_rs2;
    reg [11:0] ra_imm_31_20;
    reg [1:0] ra_aluop, ra_instr_type;
    reg [6:0] ra_opcode, ra_imm_31_25;
    reg [31:0] ra_program_counter;

    always @(posedge clk) begin
        if (!rst) begin
            ra_rs1 <= 5'b0;
            ra_rs2 <= 5'b0;
            ra_rd <= 5'b0;
            ra_imm_31_20 <= 12'b0;
            ra_aluop <= 2'b0;
            ra_instr_type <= 2'b0;
            ra_opcode <= 7'b0;
            ra_imm_31_25 <= 7'b0;
            ra_program_counter <= 32'b0;
        end else if (data_hazard) begin
            //! Mux for NOP insertion on hazard
            ra_rs1 <= 5'b0;
            ra_rs2 <= 5'b0;
            ra_rd <= 5'b0;
            ra_imm_31_20 <= 12'b0;
            ra_aluop <= `ALU_ADD;
            ra_instr_type <= `INSTR_TYPE_R;
            ra_opcode <= 7'b0;
            ra_imm_31_25 <= 7'b0;
            ra_program_counter <= if_program_counter;
        end else begin
            ra_rs1 <= fd_rs1;
            ra_rs2 <= fd_rs2;
            ra_rd <= fd_rd;
            ra_imm_31_20 <= fd_imm_31_20;
            ra_imm_31_25 <= fd_imm_31_25;
            ra_aluop <= fd_aluop;
            ra_instr_type <= fd_instr_type;
            ra_opcode <= fd_opcode;
            ra_program_counter <= if_program_counter;
        end
    end

    //! =========================================================================
    //! STAGE 3: REGFILE & ALU 
    //! =========================================================================
    wire [31:0] ra_o_reg_a, ra_o_reg_b, ra_alu_in_b, ra_alu_in_a, ra_alu_out, alu_mul_out;
    wire ra_zero, ra_is_beq;
    wire [31:0] ra_beq_offset;
    wire [31:0] ra_imm_i_type, ra_imm_s_type;
    wire ra_is_mul;

    assign ra_is_mul = (ra_opcode == `OP_R_TYPE);
    wire ra_wen = ((ra_instr_type == `INSTR_TYPE_R) || (ra_instr_type == `INSTR_TYPE_I) || ra_is_mul) && (ra_rd != 5'b0);
    
    //! To use a synchronous Regfile, read addresses must be supplied from the Decode stage
    Regfile regfile_inst (
        .clk(clk), .rst(rst), .i_wen(wb_wen), .i_wdata(wb_wdata), 
        .i_addr_a(mux_fd_rs1), .i_addr_b(mux_fd_rs2), .i_waddr(mw_rd), 
        .o_reg_a(ra_o_reg_a), .o_reg_b(ra_o_reg_b)
    );

    assign ra_imm_i_type = {{20{ra_imm_31_20[11]}}, ra_imm_31_20};
    assign ra_imm_s_type = {{20{ra_imm_31_25[6]}}, ra_imm_31_25, ra_rd};
    assign ra_alu_in_b = (ra_opcode == `OP_LW || ra_instr_type == `INSTR_TYPE_I) ? ra_imm_i_type :
                         (ra_opcode == `OP_SW) ? ra_imm_s_type : ra_o_reg_b;

    ALU alu_inst (
        .clk(clk),
        .i_operand_a(ra_o_reg_a), 
        .i_operand_b(ra_alu_in_b), 
        .i_alu_op(ra_aluop), 
        .i_mul_valid(1'b0), //! Temporarily zero.
        .o_alu_out(ra_alu_out), 
        .o_alu_zero(ra_zero),
        .o_mul_out(alu_mul_out)
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
            mul1_rd <= ra_rd;
            mul2_rd <= mul1_rd;
            mul3_rd <= mul2_rd;
            
            mul1_valid <= ra_is_mul && !(fd_wen && (fd_rd == ra_rd));
            mul2_valid <= mul1_valid && !(fd_wen && (fd_rd == mul1_rd));
            mul3_valid <= mul2_valid && !(fd_wen && (fd_rd == mul2_rd));
        end
    end

    assign ra_is_beq = (ra_opcode == `OP_BEQ);
    assign ra_branch_taken = ra_is_beq && ra_zero;

    HazardUnit hazard_unit_inst (
        .i_fd_rs1(fd_rs1),
        .i_fd_rs2(fd_rs2),
        .i_ra_wen(ra_wen),
        .i_ra_rd(ra_rd),
        .i_mul1_valid(mul1_valid),
        .i_mul1_rd(mul1_rd),
        .i_mul2_valid(mul2_valid),
        .i_mul2_rd(mul2_rd),
        .i_branch_taken(ra_branch_taken),
        .o_data_hazard(data_hazard)
    );

    assign ra_beq_offset = {{20{ra_imm_31_25[6]}}, ra_rd[0], ra_imm_31_25[5:0], ra_rd[4:1], 1'b0};
    assign ra_beq_target_idx = ra_program_counter[31:2] + ra_beq_offset[31:2];

    //* =========================================================================
    //* PIPELINE REGISTER 3: REGFILE & ALU -> LSU
    //* =========================================================================
    reg [31:0] mw_alu_out, mw_reg_b;
    reg [6:0] mw_opcode;
    reg [1:0] mw_instr_type;
    wire mw_is_mul;
    reg mw_mul3_valid;

    always @(posedge clk) begin
        if (!rst) begin
            mw_alu_out <= 32'b0;
            mw_reg_b <= 32'b0;
            mw_rd <= 5'b0;
            mw_opcode <= 7'b0;
            mw_instr_type <= 2'b0;
            mw_mul3_valid <= 1'b0;
        end else begin
            mw_alu_out <= ra_alu_out;
            mw_reg_b <= ra_o_reg_b;
            mw_mul3_valid <= mul3_valid;
            mw_rd <= mul3_valid ? mul3_rd : ra_rd;
            mw_opcode <= ra_opcode;
            mw_instr_type <= ra_instr_type;
        end
    end

    //! =========================================================================
    //! STAGE 4: MEMORY & WB
    //! =========================================================================
    (* dont_touch = "true" *) wire mw_is_load, mw_is_store;
    (* dont_touch = "true" *) wire [31:0] mw_mem_out;

    assign mw_is_load = (mw_opcode == `OP_LW);
    assign mw_is_store = (mw_opcode == `OP_SW);

    Memory dataMemory (.clk(clk), .rst(rst), .i_read_addr(mw_alu_out[11:2]), .i_read_enable(mw_is_load),
                       .i_write_addr(mw_alu_out[11:2]), .i_write_enable(mw_is_store), .i_write_data(mw_reg_b),
                       .o_out(mw_mem_out));

    assign mw_is_mul = mw_mul3_valid;
    
    assign wb_wdata = mw_is_mul ? alu_mul_out : (mw_is_load ? mw_mem_out : mw_alu_out);
    assign wb_wen = ((mw_instr_type == `INSTR_TYPE_R) || (mw_instr_type == `INSTR_TYPE_I) || mw_is_mul) && (mw_rd != 5'b0);

    assign o_leds[0] = ^mw_mem_out;
    assign o_leds[1] = ^ra_alu_out;
    assign o_leds[2] = ^mw_reg_b;
endmodule