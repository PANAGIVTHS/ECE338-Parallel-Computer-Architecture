module StreamingProcessor (
    input clk,
    input rst
);

    wire [31:0] instruction, instr_addr;
    wire [29:0] instr_idx;
    wire [31:0] alu_in_a, alu_in_b;
    wire [31:0] o_reg_b;
    wire [31:0] alu_out;
    wire [6:0] imm_31_25;
    wire [11:0] imm_31_20;
    wire [1:0] aluop, instr_type;
    wire [4:0] rs1, rs2, rd;
    wire zero, wen;

    // TODO: set values when we implement branching and jumping
    //! Counter returns instruction index not address!
    GUCounter #(.BITS(30)) 
        program_counter_inst (.clk(clk), .i_set_reset({rst, 1'b0}), .i_count_enable(1'b1), .i_count_set(30'b0), .o_count_cur(instr_idx));
    
    assign instr_addr = {instr_idx, 2'b00};
    
    // TODO: add instruction fetch module to get instruction from memory 

    Decoder decoder_inst (.i_dec_instr(instruction), .o_dec_rs1(rs1), .o_dec_rs2(rs2), .o_dec_rd(rd), .o_dec_imm_31_25(imm_31_25), .o_dec_imm_31_20(imm_31_20), .o_dec_aluop(aluop), .o_dec_instr_type(instr_type));

    // TODO: add logic to determine register addresses based on instruction type (R-type, I-type, etc.) (Maybe we can always return both rs1 and rs2 and just ignore one of them for some types)
    Regfile regfile_inst (.clk(clk), .rst(rst), .i_reg_wen(wen), .i_reg_wdata(alu_out), .i_reg_addr_a(rs1), .i_reg_addr_b(rs2), .i_reg_waddr(rd), .o_reg_a(alu_in_a), .o_reg_b(o_reg_b));

    // TODO: add logic to determine ALU inputs based on instruction type (R-type, I-type, etc.)
    assign alu_in_b = (instr_type == `INSTR_TYPE_I) ? {{20{imm_31_20[11]}}, imm_31_20} : o_reg_b;

    ALU alu_inst (.i_operand_a(alu_in_a), .i_operand_b(alu_in_b), .i_alu_op(aluop), .o_alu_out(alu_out), .o_alu_zero(zero));
    // TODO: add logic to determine when to write back to regfile
    // TODO: and determine the data to write back Load vs ALU output
    
    
    // TODO: add memory module

endmodule
