module HazardUnit (
    input [4:0] i_id_rs1,
    input [4:0] i_id_rs2,
    input [4:0] i_idex_rd,
    input i_is_load,
    input i_ex_wen,

    input [4:0] i_mul1_rd,
    input i_mul1_valid,
    input [4:0] i_mul2_rd,
    input i_mul2_valid,
    
    input i_branch_taken,
    output reg o_data_hazard
);

    always @(*) begin
        //! Standard ALU RAW Hazard
        if (i_is_load && (i_idex_rd != 5'b0) && (i_id_rs1 == i_idex_rd || i_id_rs2 == i_idex_rd)) begin
            o_data_hazard = 1'b1;
        //! Multiplier RAW Hazards
        end else begin 
            o_data_hazard = 1'b0;
        end
        //  else if (i_mul1_valid && (i_mul1_rd != 5'b0) && (i_id_rs1 == i_mul1_rd || i_id_rs2 == i_mul1_rd)) begin
        //     o_data_hazard = 1'b1;
        // //! Stall to prevent simultaneous writeback with ADD/SUB/DIV
        // end else if (i_mul2_valid && (i_mul2_rd != 5'b0)) begin
        //     o_data_hazard = 1'b1;
        // end else if (i_branch_taken) begin
        //     o_data_hazard = 1'b1;
        // end else begin
        //     o_data_hazard = 1'b0;
        // end
    end
endmodule