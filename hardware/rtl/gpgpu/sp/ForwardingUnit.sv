module ForwardingUnit
    import gpu_pkg::*;
    import riscv_pkg::*;
    import pipeline_pkg::*;
(
    input reg_addr_t i_idex_rs1,
    input reg_addr_t i_idex_rs2,
    input reg_addr_t i_exmem_rd,
    input logic i_exmem_wen,
    input reg_addr_t i_memwb_rd,
    input logic i_memwb_wen,
    input instr_type_t i_idex_instr_type,
    output forward_sel_t o_forward_alu_a,
    output forward_sel_t o_forward_alu_b
);
    always_comb begin
        o_forward_alu_a = NO_DEP;
        o_forward_alu_b = NO_DEP;

        //! Forward ALU operand A
        if (i_exmem_wen && (i_exmem_rd != '0) && (i_exmem_rd == i_idex_rs1)) begin
            o_forward_alu_a = EXALU_MEMALU_DEP;
        end else if (i_memwb_wen && (i_memwb_rd != '0) && (i_memwb_rd == i_idex_rs1)) begin
            o_forward_alu_a = MEMWB_EXALU_DEP;
        end

        //! Forward ALU operand B
        if (i_idex_instr_type != INSTR_TYPE_I) begin
            if (i_exmem_wen && (i_exmem_rd != '0) && (i_exmem_rd == i_idex_rs2)) begin
                o_forward_alu_b = EXALU_MEMALU_DEP;
            end else if (i_memwb_wen && (i_memwb_rd != '0) && (i_memwb_rd == i_idex_rs2)) begin
                o_forward_alu_b = MEMWB_EXALU_DEP;
            end
        end
    end
endmodule