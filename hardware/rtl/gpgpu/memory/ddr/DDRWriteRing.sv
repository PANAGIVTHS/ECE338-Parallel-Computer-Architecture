module DDRWriteRing 
    import DDRBackendPkg::*;
    import MemorySubsystemPkg::*;
    import AXI4FullPkg::*;
#(
    parameter int unsigned NUM_REQ
) (
    input logic clk,
    input logic rst_n,

    // For AXI Channel
    input logic aw_ready,
    input logic w_ready,
    input logic b_valid,
    input axi_resp_t b_resp,
    output logic w_valid,
    output logic w_last,
    output logic wr_owed,
    output cmd_t aw_cmd, // For last accepted group (AW channel)

    // For accepting groups
    output logic free, // A slot is free, and the AW register will be when the beats arrive
    output logic slot_free, // A slot is free (registers only)
    output ring_index_t wr_alloc, // Next free slot
    
    // Formed group: pushed into a slot, then its beats in the next cycle
    input logic push_wr, // Push new group into a slot
    input logic wr_cmd, // The group pushed last cycle: its address and beats
    input ring_group_t cmd_group,
    input beat_t first_beat, 
    input beat_t last_beat,

    // Members valid and ready masks, index per member
    input logic [NUM_REQ-1:0] wr_members,
    input ring_index_t[NUM_REQ-1:0] idx,
    input logic [NUM_REQ-1:0] wr_take,

    // For write assembler
    output beat_t w_wbeat_next, // Beat within the group offered next cycle
    output ring_index_t w_slot_next, // Slot whose burst W offers next cycle
    // For DDR interface
    output logic [NUM_REQ-1:0] wr_bdone, // (B channel)
    output axi_resp_t[NUM_REQ-1:0] wr_bresp, // (B channel)
    
    // State
    output logic busy,
    output logic fatal,
    output mem_fatal_t fatal_code
);

    localparam int unsigned WR_DEPTH = AXI_MAX_OUTSTANDING_WRITES;
    localparam int unsigned SLOT_W = $clog2(WR_DEPTH);
    typedef logic [SLOT_W:0] wr_ptr_t; // [2:0] slot index, [3] wrap bit
    typedef logic [SLOT_W-1:0] wr_slot_idx_t;

    // Pointers wrap naturally only at a power of two
    if ((WR_DEPTH & (WR_DEPTH - 1)) != 0) begin : g_depth_check
        $fatal(1, "AXI_MAX_OUTSTANDING_WRITES (%0d) must be a power of two", WR_DEPTH);
    end

    typedef struct packed {
        beat_t first; //first beat
        beat_t len; // last - first
        logic b_done; 
        axi_resp_t bresp;
    } wr_slot_t;

    //& =============================================
    //& General handshakes
    //& =============================================
    logic aw_fire, w_fire, b_fire;
    assign aw_fire = aw_ready & aw_cmd.valid;
    assign w_fire = w_ready & w_valid;
    assign b_fire = b_valid;

    //& =============================================
    //& AW command register, empties when AW channel 
    //& handshakes and fills the cycle after a group is
    //& pushed to a slot, when its beats arrive
    //& =============================================
    beat_t length;
    assign length = last_beat - first_beat;

    always_ff @(posedge clk) begin
        if (~rst_n) begin
            aw_cmd <= '0;
        end else if (wr_cmd) begin
            aw_cmd <= cmd_t'{
                valid: 1'b1,
                addr: axi_addr_t'(word_of(cmd_group, first_beat)),
                len: axi_len_t'(length)
            };
        end else if (aw_fire) begin
            aw_cmd <= '0;
        end
    end

    //& =============================================
    //& Pointers
    //& =============================================
    wr_ptr_t alloc, w, b, head;
    wr_ptr_t w_next;
    logic empty, full, pop;

    // Slot indices: the pointers without their wrap bit
    wr_slot_idx_t alloc_idx, cmd_idx, w_idx, w_next_idx, b_idx, head_idx;
    assign alloc_idx = alloc[SLOT_W-1:0];
    // The slot pushed last cycle: no push follows one directly (see free)
    assign cmd_idx = alloc_idx - wr_slot_idx_t'(1);
    assign w_idx = w[SLOT_W-1:0];
    assign w_next_idx = w_next[SLOT_W-1:0];
    assign b_idx = b[SLOT_W-1:0];
    assign head_idx = head[SLOT_W-1:0];

    assign w_next = w + wr_ptr_t'(1);
    assign empty = (head == alloc);
    assign full = (head_idx == alloc_idx) & (head[SLOT_W] != alloc[SLOT_W]);
    // AW of slot w has gone: when w is the newest slot, its AW is neither
    // in the AW register nor still to arrive
    assign w_valid = (w != alloc) & ~((aw_cmd.valid | wr_cmd) & (w_next == alloc));

    // Allocation pointer
    always_ff @(posedge clk) begin
        if (~rst_n) begin
            alloc <= '0;
        end else if (push_wr) begin
            alloc <= alloc + wr_ptr_t'(1);
        end
    end

    // Write pointer
    always_ff @(posedge clk) begin
        if (~rst_n) begin
            w <= '0;
        end else if (w_fire & w_last) begin
            w <= w_next;
        end
    end

    // Response pointer
    always_ff @(posedge clk) begin
        if (~rst_n) begin
            b <= '0;
        end else if (b_fire) begin
            b <= b + wr_ptr_t'(1);
        end
    end

    // Head
    always_ff @(posedge clk) begin
        if (~rst_n) begin
            head <= '0;
        end else if (pop) begin
            head <= head + wr_ptr_t'(1);
        end
    end

    //& =============================================
    //& Counters
    //& =============================================
    beat_t w_beat;

    // Beat counter inside a burst
    always_ff @(posedge clk) begin
        if (~rst_n) begin
            w_beat <= '0;
        end else if (w_fire & w_last) begin
            w_beat <= '0;
        end else if(w_fire) begin
            w_beat <= w_beat + beat_t'(1);
        end
    end

    //& =============================================
    //& Slots
    //& =============================================
    wr_slot_t slot[WR_DEPTH];

    always_ff @(posedge clk) begin
        if (~rst_n) begin
            for (int unsigned i = 0; i < WR_DEPTH; i++) begin
                slot[i] <= '0;
            end
        end else begin
            if (push_wr) begin
                slot[alloc_idx].b_done <= 1'b0;
                slot[alloc_idx].bresp <= AXI_RESP_OKAY;
            end
            if (wr_cmd) begin
                slot[cmd_idx].first <= first_beat;
                slot[cmd_idx].len <= length;
            end
            if (b_fire) begin
                slot[b_idx].b_done <= 1'b1;
                slot[b_idx].bresp <= b_resp;
            end
            if (pop) begin
                slot[head_idx].b_done <= 1'b0;
            end
        end
    end

    logic [NUM_REQ-1:0] waiting_at_head; 
    for (genvar i = 0; i < NUM_REQ; i++) begin: head_waiting
        assign waiting_at_head[i] = wr_members[i] & (wr_slot_idx_t'(idx[i]) == head_idx) & ~wr_take[i];
    end
    assign pop = ~empty & slot[head_idx].b_done & ~|waiting_at_head;

    //& =============================================
    //& Current W slot: its length and the beat being
    //& sent within the group, in registers so that the
    //& write assembler starts from flip-flops
    //& =============================================
    beat_t w_len, w_group_beat;

    beat_t w_len_next, w_group_beat_next;

    always_comb begin
        w_len_next = w_len;
        w_group_beat_next = w_group_beat;
        if (w_fire & w_last) begin
            // The next slot is written already, unless it is pushed now: then
            // its W waits for its AW, and the reload below catches up
            w_len_next = slot[w_next_idx].len;
            w_group_beat_next = slot[w_next_idx].first;
        end else if (w_fire) begin
            w_group_beat_next = w_group_beat + beat_t'(1);
        end else if (~w_valid) begin
            // No burst in progress (once offered, W stays valid to its last beat)
            w_len_next = slot[w_idx].len;
            w_group_beat_next = slot[w_idx].first;
        end
    end

    always_ff @(posedge clk) begin
        if (~rst_n) begin
            w_len <= '0;
            w_group_beat <= '0;
        end else begin
            w_len <= w_len_next;
            w_group_beat <= w_group_beat_next;
        end
    end

    //& =============================================
    //& Outputs
    //& =============================================
    // The write assembler registers which requests the next beat carries
    assign w_wbeat_next = w_group_beat_next;
    assign wr_owed = b != w;
    assign w_slot_next = ring_index_t'((w_fire & w_last) ? w_next_idx : w_idx);
    assign w_last = w_beat == w_len;
    assign wr_alloc = ring_index_t'(alloc_idx);

    for (genvar i = 0; i < NUM_REQ; i++) begin : wr_response
        assign wr_bdone[i] = wr_members[i] & slot[wr_slot_idx_t'(idx[i])].b_done;
        assign wr_bresp[i] = slot[wr_slot_idx_t'(idx[i])].bresp;
    end

    assign busy = ~empty;
    // The AW register takes the beats in the cycle after a push, so the
    // register must be empty by then and the cycle after a push takes none
    assign free = ~full & ~wr_cmd & (~aw_cmd.valid | aw_ready);
    assign slot_free = ~full;

    // Fatal faults
    logic stray_b, cmd_overrun, push_full;
    assign stray_b = b_valid & (b == w);
    assign cmd_overrun = wr_cmd & aw_cmd.valid & ~aw_ready;
    assign push_full = push_wr & full;
    assign fatal = stray_b | cmd_overrun | push_full;
    assign fatal_code = stray_b ? FATAL_UNEXPECTED
                    : (cmd_overrun | push_full) ? FATAL_INTERNAL
                    : FATAL_NONE;
    
endmodule
