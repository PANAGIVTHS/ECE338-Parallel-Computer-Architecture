// DDRReadRing: the read slots (docs/memory-subsystem-spec-revJ.md §6.7.3).
//
// One slot per read burst in flight, in AR order. The AR command register
// always holds the newest slot's burst. R beats arrive in order for the
// oldest slot (head); each beat serves every member waiting in that slot for
// that group beat, and the slot pops with its last beat.
module DDRReadRing
    import DDRBackendPkg::*;
    import MemorySubsystemPkg::*;
    import AXI4FullPkg::*;
#(
    parameter int unsigned NUM_REQ
) (
    input logic clk,
    input logic rst_n,

    // For AXI channel
    input logic ar_ready,
    input logic r_valid,
    input logic r_last,
    output logic r_ready,
    output logic rd_owed, // a burst has sent its AR and still expects beats
    output cmd_t rd_cmd, // For last accepted group (AR channel)

    // For accepting groups
    output logic free, // AR command register free and a slot is free
    output ring_index_t rd_alloc, // Next free slot

    // Formed group
    input logic push_rd, // Push new group into a slot
    input ring_group_t group_address,
    input beat_t first_beat,
    input beat_t last_beat,

    // Held requests, members valid and ready masks, index per member
    input mem_req_t [NUM_REQ-1:0] req,
    input logic [NUM_REQ-1:0] rd_members,
    input ring_index_t[NUM_REQ-1:0] idx,
    input logic [NUM_REQ-1:0] rd_take,

    // For DDR interface: the beat on the bus serves this member
    output logic [NUM_REQ-1:0] rd_sel,

    // State
    output logic busy,
    output logic fatal,
    output mem_fatal_t fatal_code
);

    localparam int unsigned RD_DEPTH = AXI_MAX_OUTSTANDING_READS;
    localparam int unsigned SLOT_W = $clog2(RD_DEPTH);
    typedef logic [SLOT_W:0] rd_ptr_t; // [SLOT_W-1:0] slot index, [SLOT_W] wrap bit
    typedef logic [SLOT_W-1:0] rd_slot_idx_t;

    // Pointers wrap naturally only at a power of two
    if ((RD_DEPTH & (RD_DEPTH - 1)) != 0) begin : g_depth_check
        $fatal(1, "AXI_MAX_OUTSTANDING_READS (%0d) must be a power of two", RD_DEPTH);
    end

    typedef struct packed {
        beat_t first; // first beat
        beat_t len; // last - first
    } rd_slot_t;

    //& =============================================
    //& General handshakes
    //& =============================================
    logic ar_fire, r_fire;
    assign ar_fire = ar_ready & rd_cmd.valid;
    assign r_fire = r_valid & r_ready;

    //& =============================================
    //& AR command register, empties when AR channel
    //& handshakes and fills when new group is pushed to a slot
    //& =============================================
    beat_t length;
    assign length = last_beat - first_beat;

    always_ff @(posedge clk) begin
        if (~rst_n) begin
            rd_cmd <= '0;
        end else if (push_rd) begin
            rd_cmd <= cmd_t'{
                valid: 1'b1,
                addr: axi_addr_t'(word_of(group_address, first_beat)),
                len: axi_len_t'(length)
            };
        end else if (ar_fire) begin
            rd_cmd <= '0;
        end
    end

    //& =============================================
    //& Pointers
    //& =============================================
    rd_ptr_t alloc, head, head_next;
    logic empty, full, final_beat, pop;

    // Slot indices: the pointers without their wrap bit
    rd_slot_idx_t alloc_idx, head_idx;
    assign alloc_idx = alloc[SLOT_W-1:0];
    assign head_idx = head[SLOT_W-1:0];

    assign head_next = head + rd_ptr_t'(1);
    assign empty = (head == alloc);
    assign full = (head_idx == alloc_idx) & (head[SLOT_W] != alloc[SLOT_W]);
    assign pop = r_fire & final_beat;

    // Allocation pointer
    always_ff @(posedge clk) begin
        if (~rst_n) begin
            alloc <= '0;
        end else if (push_rd) begin
            alloc <= alloc + rd_ptr_t'(1);
        end
    end

    // Head: the burst R is delivering
    always_ff @(posedge clk) begin
        if (~rst_n) begin
            head <= '0;
        end else if (pop) begin
            head <= head_next;
        end
    end

    //& =============================================
    //& Counters
    //& =============================================
    beat_t beat; // beats of burst head already received

    always_ff @(posedge clk) begin
        if (~rst_n) begin
            beat <= '0;
        end else if (pop) begin
            beat <= '0;
        end else if (r_fire) begin
            beat <= beat + beat_t'(1);
        end
    end

    //& =============================================
    //& Slots
    //& =============================================
    rd_slot_t slot[RD_DEPTH];

    always_ff @(posedge clk) begin
        if (~rst_n) begin
            for (int unsigned i = 0; i < RD_DEPTH; i++) begin
                slot[i] <= '0;
            end
        end else if (push_rd) begin
            slot[alloc_idx] <= '{first: first_beat, len: length};
        end
    end

    //& =============================================
    //& Beat delivery: every member of the head slot asking for the current
    //& group beat takes it; R waits until all of them take it
    //& =============================================
    beat_t cur_beat;
    assign cur_beat = slot[head_idx].first + beat;
    assign final_beat = beat == slot[head_idx].len;

    logic [NUM_REQ-1:0] at_head, match;
    for (genvar i = 0; i < NUM_REQ; i++) begin : beat_match
        assign at_head[i] = rd_members[i] & (rd_slot_idx_t'(idx[i]) == head_idx);
        assign match[i] = at_head[i] & (beat_of(req[i].addr) == cur_beat);
        assign rd_sel[i] = match[i] & r_valid;
    end

    assign r_ready = ~|(match & ~rd_take);

    //& =============================================
    //& Outputs
    //& =============================================
    assign rd_owed = ~empty & ~(rd_cmd.valid & (head_next == alloc)); // the head's AR has gone
    assign rd_alloc = ring_index_t'(alloc_idx);
    assign busy = ~empty;
    assign free = ~full & (~rd_cmd.valid | ar_ready);

    // Fatal faults
    logic stray_r, wrong_last, cmd_overrun, push_full, left_behind;
    assign stray_r = r_valid & ~rd_owed;
    assign wrong_last = r_fire & (r_last != final_beat);
    assign cmd_overrun = push_rd & rd_cmd.valid & ~ar_ready;
    assign push_full = push_rd & full;
    assign left_behind = pop & |(at_head & ~rd_take); // a member of the popped slot was never served
    assign fatal = stray_r | wrong_last | cmd_overrun | push_full | left_behind;
    assign fatal_code = stray_r ? FATAL_UNEXPECTED
                    : wrong_last ? FATAL_RLAST
                    : (cmd_overrun | push_full | left_behind) ? FATAL_INTERNAL
                    : FATAL_NONE;

endmodule
