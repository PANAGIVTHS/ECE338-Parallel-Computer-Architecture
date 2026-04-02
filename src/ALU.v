module ALU (out, zero, in_a, in_b, op);
    output reg [31:0] out;
    output reg zero;

    input [31:0] in_a;
    input [31:0] in_b;
    input [3:0] op;

    localparam ALU_ADD = 4'b0000;
    localparam ALU_SUB = 4'b0001;
    localparam ALU_MUL = 4'b0010;
    localparam ALU_DIV = 4'b0011;

    always @(op, in_a, in_b) begin
        case (op)
            ALU_ADD: out = in_a + in_b;
            ALU_SUB: out = in_a - in_b;
            ALU_MUL: out = in_a * in_b;
            ALU_DIV: out = in_a / in_b;
            default: out = 32'b0;
        endcase
        zero = out == 0;
    end
endmodule
