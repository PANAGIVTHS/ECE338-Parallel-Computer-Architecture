module StreamingProcessor (
    input clk,
    input rst
);

    wire [31:0] instruction;
    wire [31:0] alu_in_a, alu_in_b;
    wire [31:0] alu_out;
    wire [31:25] imm_31_25;
    wire [1:0] aluop;
    wire rs1, rs2, rd;
    wire zero, wen;

    // TODO: add instruction fetch module to get instruction from memory 

    Decoder decoder_inst (.i_dec_instr(instruction), .o_dec_rs1(rs1), .o_dec_rs2(rs2), .o_dec_rd(rd), .o_dec_imm_31_25(imm_31_25), .o_dec_aluop(aluop));

    // TODO: add logic to determine register addresses based on instruction type (R-type, I-type, etc.) (Maybe we can always return both rs1 and rs2 and just ignore one of them for some types)
    
    Regfile regfile_inst (.clk(clk), .rst(rst), .i_reg_wen(wen), .i_reg_wdata(alu_out), .i_reg_addr_a(rs1), .i_reg_addr_b(rs2), .i_reg_waddr(rd), .o_reg_a(alu_in_a), .o_reg_b(alu_in_b));

    // TODO: add logic to determine ALU inputs based on instruction type (R-type, I-type, etc.)

    ALU alu_inst (.i_operand_a(alu_in_a), .i_operand_b(alu_in_b), .i_alu_op(aluop), .o_alu_out(alu_out), .o_alu_zero(zero));
    // TODO: add logic to determine when to write back to regfile
    // TODO: and determine the data to write back Load vs ALU output
    // TODO: add memory module

endmodule;
