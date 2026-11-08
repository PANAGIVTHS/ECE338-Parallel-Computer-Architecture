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
    output mem_fatal_t o_fatal_code
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
    // The requests as the port controllers registered them: the backends
    // read these flip-flops, not the requesters' far-off pipeline registers
    mem_req_t [NUM_REQ-1:0] req_q;
    logic [NUM_REQ-1:0] req_valid;
    logic [NUM_REQ-1:0] rsp_ready;
    logic [NUM_REQ-1:0] port_idle;

    BRAMBackendInterface bram_if [NUM_REQ] ();
    DDRBackendInterface ddr_if [NUM_REQ] ();
    beat_rdata_t ddr_rd_beat;
    axi_resp_t   ddr_rd_resp;
    ring_index_t ddr_alloc;
    logic bram_busy, ddr_busy;

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
            .o_req_q(req_q[i]),
            .rsp(memory_if[i].rsp),
            .bram_if(bram_if[i]),
            .ddr_if(ddr_if[i]),
            .i_ddr_rd_beat(ddr_rd_beat),
            .i_ddr_rd_resp(ddr_rd_resp),
            .i_ddr_alloc(ddr_alloc),
            .o_idle(port_idle[i])
        );
    end

    BRAMBackend #(
        .NUM_REQ(NUM_REQ),
        .BRAM_INIT(BRAM_INIT)
    ) bramBackend (
        .clk(clk),
        .rst_n(rst_n),
        .req(req_q),
        .bram_if(bram_if),
        .o_busy(bram_busy)
    );

    DDRBackend #(
        .NUM_REQ(NUM_REQ)
    ) ddrBackend (
        .clk(clk),
        .rst_n(rst_n),
        .req(req_q),
        .axi_if(axi_if),
        .ddr_if(ddr_if),
        .o_rd_beat(ddr_rd_beat),
        .o_rd_resp(ddr_rd_resp),
        .o_alloc(ddr_alloc),
        .o_busy(ddr_busy),
        .o_fatal(o_fatal),
        .o_fatal_code(o_fatal_code)
    );

    assign o_idle = (&port_idle) & ~bram_busy & ~ddr_busy & ~o_fatal;

endmodule
