module MemorySubsystem 
    import DDRBackendPkg::*;
    import MemorySubsystemPkg::*;
    import AXI4FullPkg::*;
#(
    parameter int unsigned NUM_REQ = 32,
    parameter BRAM_INIT = "",
    parameter bit ARB_RR = 1'b0,
    parameter bit DDR_ENABLE
) (
    input logic clk,
    input logic rst_n,
    input logic i_req_enable,

    MemorySubsystemInterface.responder memory_if [NUM_REQ],
    AXI4FullInterface.master axi_if,

    output logic o_idle,
    output logic o_fatal,
    output mem_fatal_t o_fatal_code,

    // Performance counters, per port: a DDR store not yet admitted to the
    // write path, one admitted and waiting, and a DDR load not yet answered;
    // and a free write ring slot
    output logic [NUM_REQ-1:0] o_perf_st_waiting,
    output logic [NUM_REQ-1:0] o_perf_st_admitted,
    output logic [NUM_REQ-1:0] o_perf_ld_ddr,
    output logic o_perf_wr_slot_free,
    // The write ring (a slot's beats wait for W, slots occupied, bursts sent
    // whose B has not arrived), lane stores admitted to the DDR write path
    // this cycle, and BRAM accesses issued and picks deferred
    output logic o_perf_w_pending,
    output logic [$clog2(AXI_MAX_OUTSTANDING_WRITES):0] o_perf_wr_inflight,
    output logic [$clog2(AXI_MAX_OUTSTANDING_WRITES):0] o_perf_wr_owed,
    output logic [$clog2(NUM_REQ+1)-1:0] o_perf_wr_lane_stores,
    output logic [$clog2(BRAM_PORTS+1)-1:0] o_perf_bram_accesses,
    output logic [$clog2(BRAM_PORTS+1)-1:0] o_perf_bram_deferred
);
    // Elaboration-time checks
    if (ARB_RR != 1'b0) begin : g_arb_rr_check
        $fatal(1, "ARB_RR=1 (round-robin) is not supported; only fixed priority (0)");
    end

    if (!ddr_map_aligned()) begin : g_ddr_align_check
        $fatal(1, "Every DDR region base and size must be a multiple of GROUP_BYTES (%0d)",
            GROUP_BYTES);
    end

    if (!map_disjoint()) begin : g_map_overlap_check
        $fatal(1, "Memory map regions (DMEM, FB0, FB1, TEX) must not overlap");
    end
    
    // Request expansions
    mem_req_t [NUM_REQ-1:0] req;
    logic [NUM_REQ-1:0] req_valid;
    logic [NUM_REQ-1:0] rsp_ready;
    logic [NUM_REQ-1:0] port_idle;

    BRAMBackendInterface bram_if [NUM_REQ] ();
    DDRBackendInterface ddr_if [NUM_REQ] ();
    beat_rdata_t ddr_rd_beat;
    axi_resp_t   ddr_rd_resp;
    ring_index_t ddr_alloc;
    logic bram_busy, ddr_busy;
    logic [NUM_REQ-1:0] st_admit;
    assign o_perf_wr_lane_stores = $bits(o_perf_wr_lane_stores)'($countones(st_admit));

    for (genvar i = 0; i < NUM_REQ; i++) begin : gen_reqs
        assign req[i] = memory_if[i].req;
        assign req_valid[i] = memory_if[i].req_valid;
        assign rsp_ready[i] = memory_if[i].rsp_ready;
    end

    for (genvar i = 0; i < NUM_REQ; i++) begin : gen_port_controllers
        PortController #(
            .DDR_ENABLE(DDR_ENABLE)
        ) portControllers (
            .clk(clk),
            .rst_n(rst_n),
            .i_en(i_req_enable & ~o_fatal),
            .i_req_valid(req_valid[i]),
            .o_req_ready(memory_if[i].req_ready),
            .o_rsp_valid(memory_if[i].rsp_valid),
            .i_rsp_ready(rsp_ready[i]),
            .req(req[i]),
            .rsp(memory_if[i].rsp),
            .bram_if(bram_if[i]),
            .ddr_if(ddr_if[i]),
            .i_ddr_rd_beat(ddr_rd_beat),
            .i_ddr_rd_resp(ddr_rd_resp),
            .i_ddr_alloc(ddr_alloc),
            .o_idle(port_idle[i]),
            .o_perf_st_waiting(o_perf_st_waiting[i]),
            .o_perf_st_admitted(o_perf_st_admitted[i]),
            .o_perf_st_admit(st_admit[i]),
            .o_perf_ld_ddr(o_perf_ld_ddr[i])
        );
    end

    BRAMBackend #(
        .NUM_REQ(NUM_REQ),
        .BRAM_INIT(BRAM_INIT)
    ) bramBackend (
        .clk(clk),
        .rst_n(rst_n),
        .req(req),
        .bram_if(bram_if),
        .o_busy(bram_busy),
        .o_perf_accesses(o_perf_bram_accesses),
        .o_perf_deferred(o_perf_bram_deferred)
    );

    DDRBackend #(
        .NUM_REQ(NUM_REQ)
    ) ddrBackend (
        .clk(clk),
        .rst_n(rst_n),
        .req(req),
        .axi_if(axi_if),
        .ddr_if(ddr_if),
        .o_rd_beat(ddr_rd_beat),
        .o_rd_resp(ddr_rd_resp),
        .o_alloc(ddr_alloc),
        .o_busy(ddr_busy),
        .o_wr_slot_free(o_perf_wr_slot_free),
        .o_perf_w_pending(o_perf_w_pending),
        .o_perf_wr_inflight(o_perf_wr_inflight),
        .o_perf_wr_owed(o_perf_wr_owed),
        .o_fatal(o_fatal),
        .o_fatal_code(o_fatal_code)
    );

    assign o_idle = (&port_idle) & ~bram_busy & ~ddr_busy & ~o_fatal;

endmodule
