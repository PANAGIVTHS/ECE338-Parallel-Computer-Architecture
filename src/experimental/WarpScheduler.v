`timescale 1ns / 1ps

`include "../constants.vh"

module WarpScheduler #(
    parameter WARP_NUM = 32,
    parameter SLOTS = 2,
    parameter STATE_BITS = 2
)(
    input clk,
    input rst,

    //! Flattened array from WarpStateMask module
    input [(WARP_NUM * STATE_BITS)-1:0] i_all_states,

    //! Selected warp IDs
    output reg [SLOTS-1:0] o_valid,
    output reg [(SLOTS * $clog2(WARP_NUM))-1:0] o_winner_id
);

    localparam WARP_ID_BITS = $clog2(WARP_NUM);

    integer i, g, w;

    //! Tracks warps that are ready AND haven't been selected yet this cycle
    reg [WARP_NUM-1:0] ready_unissued;
    reg [WARP_NUM-1:0] current_candidates;
    
    reg [WARP_NUM-1:0] eligible_mask;
    reg [WARP_NUM-1:0] next_eligible_mask; 

    reg winner_found;
    reg [WARP_ID_BITS-1:0] winner_id;

    //& =============================================
    //& PRIORITY CASCADE SELECTION
    //& =============================================
    //! Note consider Quadrants for larger active warp counts to reduce priority cascade length

    always @(*) begin

        for (i = 0; i < WARP_NUM; i = i + 1) ready_unissued[i] = (i_all_states[(i * STATE_BITS) +: STATE_BITS] == `WARP_READY_STATE);

        next_eligible_mask = eligible_mask;

        o_valid = {SLOTS{1'b0}};
        o_winner_id = {(SLOTS * WARP_ID_BITS){1'b0}};

        //! Select up to SLOTS warps
        for (g = 0; g < SLOTS; g = g + 1) begin

            current_candidates = ready_unissued & next_eligible_mask;

            //! Refill tickets if we ran out
            if ((current_candidates == {WARP_NUM{1'b0}}) && (ready_unissued != {WARP_NUM{1'b0}})) begin
                next_eligible_mask = {WARP_NUM{1'b1}};
                current_candidates = ready_unissued;
            end

            //& -------------------------------------
            //& Priority Encoder
            //& -------------------------------------
            winner_found = 1'b0;
            winner_id = {WARP_ID_BITS{1'b0}};

            //! Lowest index gets priority
            for (w = 0; w < WARP_NUM; w = w + 1) begin
                if (!winner_found && current_candidates[w]) begin
                    winner_found = 1'b1;
                    winner_id = w[WARP_ID_BITS-1:0];
                end
            end

            //& -------------------------------------
            //& Save Winner & Consume Ticket
            //& -------------------------------------
            if (winner_found) begin
                o_valid[g] = 1'b1;
                o_winner_id[(g*WARP_ID_BITS) +: WARP_ID_BITS] = winner_id;
                
                //! Prevent this winner from being picked in subsequent slots
                ready_unissued[winner_id] = 1'b0;                
                next_eligible_mask[winner_id] = 1'b0;
            end

        end
    end

    //& =============================================
    //& UPDATE TICKETS
    //& =============================================

    always @(posedge clk) begin
        if (rst) begin
            eligible_mask <= {WARP_NUM{1'b1}};
        end else begin
            eligible_mask <= next_eligible_mask;
        end
    end

endmodule