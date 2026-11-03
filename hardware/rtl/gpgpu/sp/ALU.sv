module ALU
    import gpu_pkg::*;
    import alu_pkg::*;
(
    input word_t i_operand_a,
    input word_t i_operand_b,
    input alu_op_t i_alu_op,
    input logic i_mul_valid,
    input word_t i_mul_res,
    output word_t o_alu_out,
    output logic o_alu_zero
);
    always_comb begin
        if (i_mul_valid) begin
            o_alu_out = i_mul_res;
        end else begin 
            case (i_alu_op)
                ALU_OP_ADD: o_alu_out = i_operand_a + i_operand_b;
                ALU_OP_SUB: o_alu_out = i_operand_a - i_operand_b;
                ALU_OP_AND: o_alu_out = i_operand_a & i_operand_b;
                ALU_OP_OR:  o_alu_out = i_operand_a | i_operand_b;
                ALU_OP_XOR: o_alu_out = i_operand_a ^ i_operand_b;
                ALU_OP_SLL: o_alu_out = i_operand_a << i_operand_b[4:0];
                ALU_OP_SRA: o_alu_out = $signed(i_operand_a) >>> i_operand_b[4:0];
                ALU_OP_SRL:  o_alu_out = i_operand_a >> i_operand_b[4:0];
                ALU_OP_SLT:  o_alu_out = ($signed(i_operand_a) < $signed(i_operand_b));
                ALU_OP_SLTU: o_alu_out = (i_operand_a < i_operand_b);
                ALU_OP_LUI: o_alu_out = i_operand_b;
                default: o_alu_out = '0;
            endcase
        end
        o_alu_zero = o_alu_out == 0;
    end
endmodule