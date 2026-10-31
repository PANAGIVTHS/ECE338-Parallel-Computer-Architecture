import gpu_pkg::*;
import MemorySubsystemPkg::*;

module MemorySubsystem #(
    parameter int unsigned NUM_REQ = 32,
    parameter BRAM_INIT = "",
    parameter bit ARB_RR = 1'b0,
    parameter bit DDR_ENABLE
) (
    input logic clk,
    input logic rst_n,
    input logic i_req_enable,

    MemorySubsystemInterface.responder memory_if [NUM_REQ],

    output logic o_idle,
    output logic o_fatal,
    output mem_fatal_t o_fatal_code
);
    // Elaboration-time checks
    if (ARB_RR != 1'b0) begin : g_arb_rr_check
        $fatal(1, "ARB_RR=1 (round-robin) is not supported; only fixed priority (0)");
    end

    if (!ddr_map_aligned()) begin : g_ddr_align_check
        $fatal(1, "Every DDR region base and size must be a multiple of WINDOW_BYTES (%0d)",
            WINDOW_BYTES);
    end

    if (!map_disjoint()) begin : g_map_overlap_check
        $fatal(1, "Memory map regions (DMEM, FB0, FB1, TEX) must not overlap");
    end

    if (DDR_ENABLE) begin : g_ddr_check
        $fatal(1, "DDR_ENABLE=1: the DDR backend is not implemented yet");
    end

    mem_req_t [NUM_REQ-1:0] req;
    logic [NUM_REQ-1:0] req_valid;
    logic [NUM_REQ-1:0] rsp_ready;
    logic [NUM_REQ-1:0] is_idle;

    word_t bram_rdata [NUM_REQ-1:0];
    logic [NUM_REQ-1:0] bram_cand;
    logic [NUM_REQ-1:0] bram_take;
    logic [NUM_REQ-1:0] bram_accept;
    logic bram_busy;

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
            .en(i_req_enable),
            .rsp_ready(rsp_ready[i]),
            .req_valid(req_valid[i]),
            .req(req[i]),
            .bram_accept(bram_accept[i]),
            .bram_rdata(bram_rdata[i]),
            .ddr_accept('b0),
            .req_ready(memory_if[i].req_ready),
            .rsp_valid(memory_if[i].rsp_valid),
            .rsp(memory_if[i].rsp),
            .bram_cand(bram_cand[i]),
            .bram_take(bram_take[i]),
            .ddr_cand(),
            .is_idle(is_idle[i])
        );
    end

    BRAMBackend #(
        .NUM_REQ(NUM_REQ),
        .BRAM_INIT(BRAM_INIT)
    ) bramBackend (
        .clk(clk),
        .rst_n(rst_n),
        .req(req),
        .bram_cand(bram_cand),
        .bram_take(bram_take),
        .bram_accept(bram_accept),
        .bram_rdata(bram_rdata),
        .bram_busy(bram_busy)
    );

    assign o_idle = (&is_idle) & ~bram_busy;

    // Only the DDR backend can lock the subsystem up.
    assign o_fatal = 1'b0;
    assign o_fatal_code = FATAL_NONE;

endmodule
