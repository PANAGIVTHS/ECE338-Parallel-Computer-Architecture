module HazardUnit
    import gpu_pkg::*;
    import riscv_pkg::*;
    import pipeline_pkg::*;
(
    input reg_addr_t i_id_rs1,
    input reg_addr_t i_id_rs2,
    input reg_addr_t i_idex_rd,
    input logic i_ex_is_load,
    input logic i_ex_is_mul,
    input logic i_id_is_mul,
    input mul_hazard_t i_mul1,
    input mul_hazard_t i_mul2,
    input mul_hazard_t i_mul3,
    input instr_type_t i_id_instr_type,
    input logic i_branch_taken,
    output logic o_data_hazard,
    output logic o_flush
);

    always_comb begin
        o_data_hazard = 1'b0;
        o_flush = 1'b0;

        //! Standard ALU RAW Hazard
        if (i_ex_is_load && (i_idex_rd != '0)) begin
            if ((i_id_rs1 == i_idex_rd) ||
                ((i_id_instr_type != INSTR_TYPE_I) && (i_id_rs2 == i_idex_rd))) begin
                o_data_hazard = 1'b1;
            end
        end else if (i_branch_taken) begin
            o_data_hazard = 1'b1;
            o_flush = 1'b1;
            //! When there is a mul in EX stall, EXCEPT when the id stage is
            //! a multiplication that has no dependency on the muls that are
            //! inside EX.
        end else if ((i_ex_is_mul || i_mul1.valid || i_mul2.valid || i_mul3.valid) && !(
            i_id_is_mul &&
            
            //! 1. Check dependency against the MUL currently in the EX stage
            (i_id_rs1 != i_idex_rd) && (i_id_rs2 != i_idex_rd) &&

            //! 2. Check dependency against the MUL in the first DSP stage
            (!i_mul1.valid || ((i_id_rs1 != i_mul1.rd) && (i_id_rs2 != i_mul1.rd))) &&

            //! 3. Check dependency against the MUL in the second DSP stage
            (!i_mul2.valid || ((i_id_rs1 != i_mul2.rd) && (i_id_rs2 != i_mul2.rd))) &&

            //! 4. Check dependency against the MUL in the third DSP stage
            (!i_mul3.valid || ((i_id_rs1 != i_mul3.rd) && (i_id_rs2 != i_mul3.rd)))
        )) begin
            o_data_hazard = 1'b1;
        end
    end
endmodule