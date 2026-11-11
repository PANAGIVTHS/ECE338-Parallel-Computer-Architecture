module DDRBackend 
    import gpu_pkg::*;
    import AXI4FullPkg::*;
    import MemorySubsystemPkg::*;
    import DDRBackendPkg::*;
#(
    parameter int unsigned NUM_REQ
) (
    input logic clk,
    input logic rst_n,

    input mem_req_t [NUM_REQ-1:0] req,

    AXI4FullInterface.master axi_if,
    DDRBackendInterface.responder ddr_if [NUM_REQ],

    output beat_rdata_t o_rd_beat,
    output axi_resp_t o_rd_resp,
    output ring_index_t o_alloc,

    output logic o_busy,
    // Performance counters: the write ring has a free slot, a slot's beats
    // wait for W, slots occupied, and bursts sent whose B has not arrived
    output logic o_wr_slot_free,
    output logic o_perf_w_pending,
    output logic [$clog2(AXI_MAX_OUTSTANDING_WRITES):0] o_perf_wr_inflight,
    output logic [$clog2(AXI_MAX_OUTSTANDING_WRITES):0] o_perf_wr_owed,
    output logic o_fatal,
    output mem_fatal_t o_fatal_code
);

    // A beat holds several words: PortController selects one by address bits.
    if (AXI_DATA_W <= XLEN || AXI_DATA_W % XLEN != 0) begin : g_beat_check
        $fatal(1, "AXI_DATA_W (%0d) must be a multiple of XLEN (%0d) larger than it",
            AXI_DATA_W, XLEN);
    end

    //& =============================================
    //& Signal expansions from DDR interface
    //& =============================================
    ring_index_t[NUM_REQ-1:0] idx;
    logic [NUM_REQ-1:0] wr_take, wr_bdone;
    axi_resp_t[NUM_REQ-1:0] wr_bresp;
    logic [NUM_REQ-1:0] rd_take, rd_sel;

    for (genvar i = 0; i < NUM_REQ; i++) begin: ddr_expand
        assign idx[i] = ddr_if[i].idx;
        assign wr_take[i] = ddr_if[i].wr_take;
        assign ddr_if[i].wr_bdone = wr_bdone[i];
        assign ddr_if[i].wr_bresp = wr_bresp[i];
        assign rd_take[i] = ddr_if[i].rd_take;
        assign ddr_if[i].rd_sel = rd_sel[i];
    end

    //& =============================================
    //& Group former that selects one group per cycle
    //& for either reading or writing
    //& =============================================
    logic [NUM_REQ-1:0] cand, selected;
    logic push_rd, push_wr;
    ring_group_t group_address;
    beat_t first_beat, last_beat;
    logic rd_ring_free, wr_ring_free;

    for (genvar i = 0; i < NUM_REQ; i++) begin: cand_expand
        assign cand[i] = ddr_if[i].cand;
        assign ddr_if[i].accept = selected[i];
    end

    DDRGroupFormer #(
        .NUM_REQ(NUM_REQ)
     ) ddrGroupFormer (
        .cand         (cand),
        .req          (req),
        .rd_ring_free (rd_ring_free),
        .wr_ring_free (wr_ring_free),
        .accept       (selected),
        .push_rd      (push_rd),
        .push_wr      (push_wr),
        .group_address(group_address),
        .first_beat   (first_beat),
        .last_beat    (last_beat)
    );

    //& =============================================
    //& DDRWriteRing claims a group from GroupFormer
    //& and prepares write addresses, write data, write responses
    //& =============================================
    logic [NUM_REQ-1:0] wr_members;
    beat_t w_wbeat;
    ring_index_t wr_alloc, w_slot;
    logic wr_busy, wr_fatal;
    mem_fatal_t wr_fatal_code;
    logic aw_ready;
    logic w_valid, w_last, wr_owed;
    logic w_ready, b_valid;
    axi_resp_t b_resp;
    cmd_t aw_cmd;

    for (genvar i = 0; i < NUM_REQ; i++) begin: wr_member_expand
        assign wr_members[i] = ddr_if[i].wr_member;
    end

    DDRWriteRing #(
        .NUM_REQ(NUM_REQ)
     ) ddrWriteRing (
        .clk          (clk),
        .rst_n        (rst_n),
        // AXI channel
        .aw_ready     (aw_ready),
        .w_ready      (w_ready),
        .b_valid      (b_valid),
        .b_resp       (b_resp),
        .w_valid      (w_valid),
        .w_last       (w_last),
        .wr_owed      (wr_owed),
        .aw_cmd       (aw_cmd),
        // Group formation
        .free         (wr_ring_free),
        .slot_free    (o_wr_slot_free),
        .wr_alloc     (wr_alloc),
        .push_wr      (push_wr),
        .group_address(group_address),
        .first_beat   (first_beat),
        .last_beat    (last_beat),
        // DDR interface from requesters
        .wr_members   (wr_members),
        .idx          (idx),
        .wr_take      (wr_take),
        // DDR interface to requesters
        .wr_bdone     (wr_bdone),
        .wr_bresp     (wr_bresp),
        // For write assembler 
        .w_wbeat      (w_wbeat), // Current beat: first_beat + current
        .w_slot       (w_slot), // Slot index serving the W channel
        // Ring state
        .busy         (wr_busy),
        .fatal        (wr_fatal),
        .fatal_code   (wr_fatal_code),
        // Performance counters
        .perf_w_pending(o_perf_w_pending),
        .perf_inflight (o_perf_wr_inflight),
        .perf_owed     (o_perf_wr_owed)
    );

    //& =============================================
    //& DDRWriteAssembler builds W data from the held requests
    //& =============================================
    axi_data_t w_data;
    axi_strb_t w_strb;

    DDRWriteAssembler #(
        .NUM_REQ(NUM_REQ)
    ) ddrWriteAssembler (
        .req       (req),
        .wr_members(wr_members),
        .idx       (idx),
        .w_slot    (w_slot),
        .w_wbeat   (w_wbeat),
        .w_data    (w_data),
        .w_strb    (w_strb)
    );

    //& =============================================
    //& DDRReadRing claims a group from GroupFormer,
    //& issues its AR and hands each R beat to its members
    //& =============================================
    logic [NUM_REQ-1:0] rd_members;
    ring_index_t rd_alloc;
    logic rd_busy, rd_fatal;
    mem_fatal_t rd_fatal_code;
    cmd_t rd_cmd;
    logic rd_r_ready, rd_owed;
    logic ar_ready, r_valid, r_last;

    for (genvar i = 0; i < NUM_REQ; i++) begin: rd_member_expand
        assign rd_members[i] = ddr_if[i].rd_member;
    end

    DDRReadRing #(
        .NUM_REQ(NUM_REQ)
    ) ddrReadRing (
        .clk          (clk),
        .rst_n        (rst_n),
        // AXI channel
        .ar_ready     (ar_ready),
        .r_valid      (r_valid),
        .r_last       (r_last),
        .r_ready      (rd_r_ready),
        .rd_owed      (rd_owed),
        .rd_cmd       (rd_cmd),
        // Group formation
        .free         (rd_ring_free),
        .rd_alloc     (rd_alloc),
        .push_rd      (push_rd),
        .group_address(group_address),
        .first_beat   (first_beat),
        .last_beat    (last_beat),
        // DDR interface from requesters
        .req          (req),
        .rd_members   (rd_members),
        .idx          (idx),
        .rd_take      (rd_take),
        // DDR interface to requesters
        .rd_sel       (rd_sel),
        // Ring state
        .busy         (rd_busy),
        .fatal        (rd_fatal),
        .fatal_code   (rd_fatal_code)
    );

    //& =============================================
    //& AXI Master
    //& =============================================

    logic axi_fatal;
    mem_fatal_t axi_fatal_code;

    AXI4Master axi4Master (
        .clk        (clk),
        .rst_n      (rst_n),
        .axi_if     (axi_if),
        // Read ring
        .rd_cmd     (rd_cmd),
        .r_ready    (rd_r_ready),
        .rd_owed    (rd_owed),
        .ar_ready   (ar_ready),
        .r_valid    (r_valid),
        .r_last     (r_last),
        .r_data     (o_rd_beat),
        .r_resp     (o_rd_resp),
        // Write ring and assembler
        .wr_cmd     (aw_cmd),
        .w_valid    (w_valid),
        .w_last     (w_last),
        .w_data     (w_data),
        .w_strb     (w_strb),
        .wr_owed    (wr_owed),
        .aw_ready   (aw_ready),
        .w_ready    (w_ready),
        .b_valid    (b_valid),
        .b_resp     (b_resp),
        // Fatal
        .i_fatal    (o_fatal),
        .fatal      (axi_fatal),
        .fatal_code (axi_fatal_code)
    );

    //& =============================================
    //& Output signals
    //& =============================================
    assign o_alloc = push_wr ? wr_alloc : rd_alloc;
    assign o_busy = rd_busy | wr_busy;

    always_ff @(posedge clk) begin
        if (~rst_n) begin
            o_fatal      <= 1'b0;
            o_fatal_code <= FATAL_NONE;
        end else if (~o_fatal & (rd_fatal | wr_fatal | axi_fatal)) begin
            o_fatal      <= 1'b1;
            o_fatal_code <= rd_fatal ? rd_fatal_code
                          : wr_fatal ? wr_fatal_code
                          : axi_fatal_code;
        end
    end

endmodule
