`include "constants.vh"

module ForwardingUnit (
    input [4:0] i_idex_rs1,
    input [4:0] i_idex_rs2,
    input [4:0] i_exmem_rd,
    input i_exmem_wen,
    input [4:0] i_memwb_rd,
    input i_memwb_wen,
    output reg [1:0] o_forward_alu_a,
    output reg [1:0] o_forward_alu_b
);
    always @(*) begin
        o_forward_alu_a = `NO_DEP;
        o_forward_alu_b = `NO_DEP;

        if (i_exmem_wen && (i_exmem_rd != 5'b0) && (i_exmem_rd == i_idex_rs1)) begin
            o_forward_alu_a = `EXALU_MEMALU_DEP;
        end else if (i_memwb_wen && (i_memwb_rd != 5'b0) && (i_memwb_rd == i_idex_rs1)) begin
            o_forward_alu_a = `MEMWB_EXALU_DEP;
        end

        if (i_exmem_wen && (i_exmem_rd != 5'b0) && (i_exmem_rd == i_idex_rs2)) begin
            o_forward_alu_b = `EXALU_MEMALU_DEP;
        end else if (i_memwb_wen && (i_memwb_rd != 5'b0) && (i_memwb_rd == i_idex_rs2)) begin
            o_forward_alu_b = `MEMWB_EXALU_DEP;
        end

    end
endmodule