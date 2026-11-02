module DDRWriteAssembler
    import gpu_pkg::*;
    import AXI4FullPkg::*;
    import MemorySubsystemPkg::*;
    import DDRBackendPkg::*;
#(
    parameter int unsigned NUM_REQ
) (
    input mem_req_t [NUM_REQ-1:0] req,

    // Which ports wait in which write slot
    input logic [NUM_REQ-1:0] wr_members,
    input ring_index_t [NUM_REQ-1:0] idx,

    // Burst being sent and its current beat within the group
    input ring_index_t w_slot,
    input beat_t w_wbeat,

    output axi_data_t w_data,
    output axi_strb_t w_strb
);

    localparam int unsigned WORD_BYTES = XLEN / 8;

    //& =============================================
    //& MEMBERS IN THE CURRENT BEAT
    //& =============================================
    logic [NUM_REQ-1:0] hit;

    always_comb begin
        for (int unsigned r = 0; r < NUM_REQ; r++) begin
            hit[r] = wr_members[r] & (idx[r] == w_slot) & (beat_of(req[r].addr) == w_wbeat);
        end
    end

    //& =============================================
    //& BYTE LANES: lowest-index writer wins
    //& =============================================
    for (genvar L = 0; L < AXI_STRB_W; L++) begin : g_lane
        localparam int unsigned WORD = L / WORD_BYTES;
        localparam int unsigned BYTE = L % WORD_BYTES;

        logic [NUM_REQ-1:0] lane, top;
        logic [7:0] lane_byte;

        always_comb begin
            for (int unsigned r = 0; r < NUM_REQ; r++) begin
                lane[r] = hit[r] & (word_sel_of(req[r].addr) == word_sel_t'(WORD))
                        & req[r].wstrb[BYTE];
            end
        end

        // Same-cycle stores to one byte: which one wins is unspecified (§5.6)
        ArbiterMLowest #(
            .N(NUM_REQ),
            .M(1)
        ) writer (
            .req    (lane),
            .grant  (),
            .win_oh (top),
            .win_vld(w_strb[L]),
            .win_idx()
        );

        // One-hot AND-OR mux
        always_comb begin
            lane_byte = '0;
            for (int unsigned r = 0; r < NUM_REQ; r++) begin
                lane_byte |= {8{top[r]}} & req[r].wdata[BYTE*8 +: 8];
            end
        end

        assign w_data[L*8 +: 8] = lane_byte;
    end

endmodule