module DDRGroupFormer 
    import gpu_pkg::*;
    import DDRBackendPkg::*;
    import MemorySubsystemPkg::*;
#(
    parameter int unsigned NUM_REQ,
    localparam IDX_W = NUM_REQ > 1 ? $clog2(NUM_REQ) : 1
) (
    input logic [NUM_REQ-1:0] cand,
    input mem_req_t [NUM_REQ-1:0] req,

    // Ring availability
    input rd_ring_free,
    input wr_ring_free,

    // All accepted requsts
    output logic [NUM_REQ-1:0] accept,
    output logic push_rd, // Accepted for read
    output logic push_wr, // Accepted for write

    // Currently accepted group and its beats
    output ring_group_t group_address,
    output beat_t first_beat,
    output beat_t last_beat
);
    
    //& =============================================
    //& SEED FINDER AND MEMBER SELECTION
    //& =============================================
    
    // A group can be issued this cycle
    logic group_found;
    // Remove candidates that cannot be served by the 
    // requesting ring (ex. remove read candidates if read ring not free)
    logic [NUM_REQ-1:0] eligible;
    // Selected candidates that can be served
    logic [NUM_REQ-1:0] selected;
    logic [NUM_REQ-1:0] seed_oh;
    word_t seed_addr;
    logic seed_write;
    assign group_address = group_of(seed_addr);

    ArbiterMLowest #(
        .N(NUM_REQ),
        .M(1)
     ) arbiterMLowest (
        .req(eligible),
        .grant(),
        .win_oh(seed_oh),
        .win_vld(group_found),
        .win_idx()
    );

    always_comb begin
        seed_addr  = '0;
        seed_write = 1'b0;
        for (int unsigned i = 0; i < NUM_REQ; i++) begin
            seed_addr  |= {XLEN{seed_oh[i]}} & req[i].addr;
            seed_write |= seed_oh[i] & req[i].write;
        end
    end

    always_comb begin
        for (int unsigned i = 0; i < NUM_REQ; i++) begin
            eligible[i] = cand[i] & (req[i].write ? wr_ring_free : rd_ring_free);
        end
    end

    always_comb begin
        for (int unsigned i = 0; i < NUM_REQ; i++) begin
            selected[i] = group_found & cand[i] 
            & (group_of(req[i].addr) == group_of(seed_addr)) & (req[i].write == seed_write);
        end
    end

    //& =============================================
    //& FIRST AND LAST BEAT
    //& =============================================
    beat_t beats [NUM_REQ];
    beat_mask_t valid_beats, valid_beats_reversed;
    beat_t last_index_reversed;

    for (genvar i = 0; i < NUM_REQ; i++) begin: beat_expansion
        assign beats[i] = beat_of(req[i].addr);
    end

    // Create mask of which beats in the burst will be valid
    always_comb begin
        valid_beats = '0;

        for (int unsigned i = 0; i < NUM_REQ; i++) begin
            if (selected[i])
                valid_beats[beats[i]] = 1'b1;
        end
    end

    // Reverse the mast to find the last beat
    assign valid_beats_reversed = {<<{valid_beats}};

    ArbiterMLowest #(
        .N($bits(beat_mask_t)),
        .M(1)
    ) first_beat_arbiter (
        .req    (valid_beats),
        .grant  (),
        .win_oh (),
        .win_vld(),
        .win_idx(first_beat)
    );

    ArbiterMLowest #(
        .N($bits(beat_mask_t)),
        .M(1)
    ) last_beat_arbiter (
        .req    (valid_beats_reversed),
        .grant  (),
        .win_oh (),
        .win_vld(),
        .win_idx(last_index_reversed)
    );

    assign last_beat = ~last_index_reversed;
    
    //& =============================================
    //& RING CHECKER
    //& =============================================
    assign push_rd = group_found & rd_ring_free & ~seed_write;
    assign push_wr = group_found & wr_ring_free & seed_write;
    assign accept = selected;

endmodule
