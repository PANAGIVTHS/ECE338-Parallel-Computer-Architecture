module SP (clk, rst);
    input clk, rst;

    wire [31:0] instruction;
    wire [31:0] alu_in_a, alu_in_b;
    wire [31:0] alu_out;
    wire [31:25] imm_31_25;
    wire [1:0] aluop;
    wire rs1, rs2, rd;
    wire zero;
    wire wen;

    Decoder decoder(.instruction(instruction), .rs2(rs2), .rs1(rs1), .rd(rd), .imm_31_25(imm_31_25), .aluop(aluop));

    Regfile regfile(.clk(clk), .rst(rst), .addr_a(/* */), .addr_b(/* */), .wen(wen), .waddr(/* */), .wdata(/* */), .out_a(alu_in_a), .out_b(alu_in_b));

    ALU alu(.out(alu_out), .zero(zero), .in_a(alu_in_a), in_b(alu_in_b), .op(aluop));

    // TODO: add memory module

endmodule;
