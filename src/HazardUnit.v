module HazardUnit (
    input [4:0] i_fd_rs1,
    input [4:0] i_fd_rs2,
    input i_ra_wen,
    input [4:0] i_ra_rd,
    input i_mul1_valid,
    input [4:0] i_mul1_rd,
    input i_mul2_valid,
    input [4:0] i_mul2_rd,
    input i_branch_taken,
    output reg o_data_hazard
);

    always @(*) begin
        //! Standard ALU RAW Hazard (Stalls for 1 cycle until data reaches combinational bypass)
        if (i_ra_wen && (i_ra_rd != 5'b0) && (i_fd_rs1 == i_ra_rd || i_fd_rs2 == i_ra_rd)) begin
            o_data_hazard = 1'b1;
        //! Multiplier RAW Hazards
        end else if (i_mul1_valid && (i_mul1_rd != 5'b0) && (i_fd_rs1 == i_mul1_rd || i_fd_rs2 == i_mul1_rd)) begin
            o_data_hazard = 1'b1;
        //! Stall to prevent simultaneous writeback with ADD/SUB/DIV
        end else if (i_mul2_valid && (i_mul2_rd != 5'b0)) begin
            o_data_hazard = 1'b1;
        end else if (i_branch_taken) begin
            o_data_hazard = 1'b1;
        end else begin
            o_data_hazard = 1'b0;
        end
    end
endmodule