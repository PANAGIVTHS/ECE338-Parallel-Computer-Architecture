`timescale 1ns / 1ps

module WarpScheduler #(
    parameter WARP_NUM = 32,
    parameter SLOTS = 2,
    parameter STATE_BITS = 2,
    parameter READY_STATE = 2'b01
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

    reg [WARP_NUM-1:0] initial_ready;
    reg [WARP_NUM-1:0] eligible_mask;
    reg [WARP_NUM-1:0] current_candidates;

    //! If refilling tickets, this tracks which warps have already been selected in this epoch
    //! thus preventing them from being selected again until the next epoch
    reg [WARP_NUM-1:0] remaining_ready;

    reg epoch_reset_triggered;

    //! Winner tracking
    reg winner_found;
    reg [WARP_ID_BITS-1:0] winner_id;
    reg [WARP_NUM-1:0] winner_onehot;
    reg [WARP_NUM-1:0] accumulated_winners;

    //& =============================================
    //& PRIORITY CASCADE SELECTION
    //& =============================================
    //! Note consider Quadrants for larger active warp counts to reduce priority cascade length

    always @(*) begin

        for (i = 0; i < WARP_NUM; i = i + 1) initial_ready[i] = (i_all_states[(i * STATE_BITS) +: STATE_BITS] == READY_STATE);

        remaining_ready = initial_ready;
        current_candidates = initial_ready & eligible_mask;

        epoch_reset_triggered = 1'b0;
        accumulated_winners = {WARP_NUM{1'b0}};

        o_valid = {SLOTS{1'b0}};
        o_winner_id = {(SLOTS * WARP_ID_BITS){1'b0}};

        //! Select up to SLOTS warps
        for (g = 0; g < SLOTS; g = g + 1) begin

            //! Refill tickets if epoch ended (False epoch reset)
            if ((current_candidates == {WARP_NUM{1'b0}}) && (remaining_ready != {WARP_NUM{1'b0}})) begin
                current_candidates = remaining_ready;
                epoch_reset_triggered = 1'b1;
            end

            //& -------------------------------------
            //& Priority Encoder
            //& -------------------------------------
            winner_found = 1'b0;
            winner_id = {WARP_ID_BITS{1'b0}};
            winner_onehot = {WARP_NUM{1'b0}};

            //! Lowest index gets priority
            for (w = WARP_NUM-1; w >= 0; w = w - 1) begin
                if (!winner_found && current_candidates[w]) begin
                    winner_found = 1'b1;
                    winner_id = w[WARP_ID_BITS-1:0];
                    winner_onehot[w] = 1'b1;
                end
            end

            //& -------------------------------------
            //& Save Winner & Mask Out
            //& -------------------------------------
            if (winner_found) begin
                o_valid[g] = 1'b1;
                o_winner_id[(g*WARP_ID_BITS) +: WARP_ID_BITS] = winner_id;
                
                //! Prevent this winner from being picked in subsequent slots
                current_candidates = current_candidates & ~winner_onehot;
                remaining_ready = remaining_ready & ~winner_onehot;
                
                accumulated_winners = accumulated_winners | winner_onehot;
            end

        end
    end

    //& =============================================
    //& UPDATE TICKETS
    //& =============================================

    always @(posedge clk) begin
        if (rst) begin
            eligible_mask <= {WARP_NUM{1'b1}};
        end else if (epoch_reset_triggered) begin
            //! Refill tickets except already selected warps from the false epoch reset
            eligible_mask <= {WARP_NUM{1'b1}} & ~accumulated_winners;
        end else begin
            //! Consume tickets of selected warps
            eligible_mask <= eligible_mask & ~accumulated_winners;
        end
    end

endmodule