// DDRGroupFormer: forms AXI burst groups from the candidates.
//
// Three stages, so that picking a seed, gathering its group and finding the
// group's beats are never in the same cycle. The seed register holds the
// group being gathered (its 128-byte window and direction): every candidate
// in it is a member, and all of them are accepted together (pushed) as soon
// as the group's ring is free. In the same cycle the next seed is picked: the
// lowest-index eligible candidate outside the held group. The cycle after a
// push gives the ring the pushed group's first and last beat, for its AW
// command; the ring takes no push in that cycle, so a group is pushed at
// most every other cycle.
//
// A request stays a candidate, with the same address, until it is accepted,
// so a group still gathers every request in its window: the bursts are the
// ones a single-cycle former would make.
module DDRGroupFormer
    import gpu_pkg::*;
    import DDRBackendPkg::*;
    import MemorySubsystemPkg::*;
#(
    parameter int unsigned NUM_REQ
) (
    input logic clk,
    input logic rst_n,

    input logic [NUM_REQ-1:0] cand,
    input logic [NUM_REQ-1:0] pick, // candidates as of last cycle, from registers
    input mem_req_t [NUM_REQ-1:0] req,

    // Ring availability
    input logic rd_ring_free,
    input logic wr_ring_free,

    // All accepted requests
    output logic [NUM_REQ-1:0] accept,
    output logic push_rd, // Accepted for read
    output logic push_wr, // Accepted for write

    // The group pushed last cycle, and its beats
    output logic rd_cmd,
    output logic wr_cmd,
    output ring_group_t cmd_group,
    output beat_t first_beat,
    output beat_t last_beat
);

    //& =============================================
    //& HELD GROUP AND ITS MEMBERS
    //& =============================================
    logic seed_valid;
    ring_group_t seed_group;
    logic seed_write;

    // Requests in the held group's window and direction, candidates or not
    logic [NUM_REQ-1:0] in_group, members;

    always_comb begin
        for (int unsigned i = 0; i < NUM_REQ; i++) begin
            // Candidates are DDR accesses: comparing inside the DDR window is enough
            in_group[i] = (group_key(group_of(req[i].addr)) == group_key(seed_group)) & (req[i].write == seed_write);
        end
    end

    assign members = {NUM_REQ{seed_valid}} & cand & in_group;

    logic any_member, ring_free, push, hold;
    assign any_member = |members;
    assign ring_free = seed_write ? wr_ring_free : rd_ring_free;
    assign push = any_member & ring_free;
    // Kept until its ring is free. A group whose requests were all withdrawn
    // (the subsystem was disabled) is dropped, so it never blocks the others.
    assign hold = any_member & ~ring_free;

    //& =============================================
    //& NEXT SEED: lowest-index eligible candidate
    //& outside the held group
    //& =============================================
    logic [NUM_REQ-1:0] eligible, seed_oh;
    logic seed_found;
    word_t seed_addr;
    logic next_write;

    // Candidates the requesting ring cannot serve now are skipped, as before:
    // a read seed must not block writes while the read ring is full. A seed
    // that is no longer a candidate gathers nothing and is dropped.
    always_comb begin
        for (int unsigned i = 0; i < NUM_REQ; i++) begin
            eligible[i] = pick[i] & ~(seed_valid & in_group[i])
                        & (req[i].write ? wr_ring_free : rd_ring_free);
        end
    end

    ArbiterMLowest #(
        .N(NUM_REQ),
        .M(1)
    ) seedArbiter (
        .req    (eligible),
        .grant  (),
        .win_oh (seed_oh),
        .win_vld(seed_found),
        .win_idx()
    );

    // One-hot AND-OR mux
    always_comb begin
        seed_addr  = '0;
        next_write = 1'b0;
        for (int unsigned i = 0; i < NUM_REQ; i++) begin
            seed_addr  |= {XLEN{seed_oh[i]}} & req[i].addr;
            next_write |= seed_oh[i] & req[i].write;
        end
    end

    always_ff @(posedge clk) begin
        if (~rst_n) begin
            seed_valid <= 1'b0;
            seed_group <= '0;
            seed_write <= 1'b0;
        end else if (~hold) begin
            seed_valid <= seed_found;
            seed_group <= group_of(seed_addr);
            seed_write <= next_write;
        end
    end

    //& =============================================
    //& FIRST AND LAST BEAT OF THE GROUP PUSHED LAST CYCLE
    //& =============================================
    beat_t beats [NUM_REQ];
    beat_mask_t member_beats, valid_beats, valid_beats_reversed;
    beat_t last_index_reversed;

    for (genvar i = 0; i < NUM_REQ; i++) begin : beat_expansion
        assign beats[i] = beat_of(req[i].addr);
    end

    // Mask of the beats the held group's burst carries, registered with the push
    always_comb begin
        member_beats = '0;
        for (int unsigned i = 0; i < NUM_REQ; i++) begin
            if (members[i])
                member_beats[beats[i]] = 1'b1;
        end
    end

    always_ff @(posedge clk) begin
        if (~rst_n) begin
            rd_cmd <= 1'b0;
            wr_cmd <= 1'b0;
        end else begin
            rd_cmd <= push_rd;
            wr_cmd <= push_wr;
        end
        valid_beats <= member_beats;
        cmd_group <= seed_group;
    end

    // Reverse the mask to find the last beat
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
    assign push_rd = push & ~seed_write;
    assign push_wr = push & seed_write;
    assign accept = {NUM_REQ{push}} & members;

endmodule
