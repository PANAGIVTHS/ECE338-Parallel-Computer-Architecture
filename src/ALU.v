`include "constants.vh"

module ALU (
    input [31:0] i_operand_a,
    input [31:0] i_operand_b,
    input [1:0] i_alu_op,
    output reg [31:0] o_alu_out,
    output reg o_alu_zero
);

    always @(i_alu_op, i_operand_a, i_operand_b) begin
        case (i_alu_op)
            `ALU_ADD: o_alu_out = i_operand_a + i_operand_b;
            `ALU_SUB: o_alu_out = i_operand_a - i_operand_b;
            `ALU_MUL: o_alu_out = i_operand_a * i_operand_b;
            `ALU_DIV: o_alu_out = i_operand_a / i_operand_b;
            default: o_alu_out = 32'b0;
        endcase
        o_alu_zero = o_alu_out == 0;
    end
endmodule
