module HazardUnit (
    input [4:0] i_id_rs1,
    input [4:0] i_id_rs2,
    input [4:0] i_idex_rd,
    input i_ex_is_load,
    input i_ex_is_mul,
    input i_id_is_mul,
    input [4:0] i_mul1_rd,
    input i_mul1_valid,
    input [4:0] i_mul2_rd,
    input i_mul2_valid,
    input [4:0] i_mul3_rd,
    input i_mul3_valid,
    input [1:0] i_id_instr_type,
    input i_branch_taken,
    output reg o_data_hazard,
    output reg o_flush
);

    always @(*) begin
        o_data_hazard = 1'b0;
        o_flush = 1'b0;

        //! Standard ALU RAW Hazard
        if (i_ex_is_load && (i_idex_rd != 5'b0)) begin
            if (i_id_rs1 == i_idex_rd) begin
                o_data_hazard = 1'b1;
            end else if ((i_id_instr_type != `INSTR_TYPE_I) && (i_id_rs2 == i_idex_rd)) begin
                o_data_hazard = 1'b1;
            end else begin
                o_data_hazard = 1'b0;
            end
        end else if (i_branch_taken) begin
            o_data_hazard = 1'b1;
            o_flush = 1'b1;
            //! When there is a mul in EX stall, EXCEPT when the id stage is
            //! a multiplication that has no dependency on the muls that are
            //! inside EX.
        end else if ((i_ex_is_mul || i_mul1_valid || i_mul2_valid || i_mul3_valid) && !(
            i_id_is_mul && 
            //! 1. Check dependency against the MUL currently in the EX stage
            (i_id_rs1 != i_idex_rd) && (i_id_rs2 != i_idex_rd) && 
            
            //! 2. Check dependency against the MUL in the first DSP stage
            (!i_mul1_valid || ((i_id_rs1 != i_mul1_rd) && (i_id_rs2 != i_mul1_rd))) &&
            
            //! 3. Check dependency against the MUL in the second DSP stage
            (!i_mul2_valid || ((i_id_rs1 != i_mul2_rd) && (i_id_rs2 != i_mul2_rd))) &&

            //! 4. Check dependency against the MUL in the third DSP stage
            (!i_mul3_valid || ((i_id_rs1 != i_mul3_rd) && (i_id_rs2 != i_mul3_rd)))
        )) begin
            o_data_hazard = 1'b1;
        end
    end
endmodule