`include "constants.vh"

module ALU (
    input clk,
    input [31:0] i_operand_a,
    input [31:0] i_operand_b,
    input [1:0] i_alu_op,
    input i_mul_valid,
    output reg [31:0] o_alu_out,
    output reg o_alu_zero
);
    (* use_dsp = "yes" *) reg [31:0] mul_stage1;
    (* use_dsp = "yes" *) reg [31:0] mul_stage2;
    (* use_dsp = "yes" *) reg [31:0] mul_stage3;

    always @(posedge clk) begin
        mul_stage1 <= i_operand_a * i_operand_b;
        mul_stage2 <= mul_stage1;
        mul_stage3 <= mul_stage2;
    end
    
    always @(i_alu_op, i_operand_a, i_operand_b) begin
        if (i_mul_valid) begin
            o_alu_out = mul_stage3;
        end else begin 
            case (i_alu_op)
                `ALU_ADD: o_alu_out = i_operand_a + i_operand_b;
                `ALU_SUB: o_alu_out = i_operand_a - i_operand_b;
                `ALU_DIV: o_alu_out = i_operand_a / i_operand_b;
                default: o_alu_out = 32'b0;
            endcase
        end
        o_alu_zero = o_alu_out == 0;
    end
endmodule
