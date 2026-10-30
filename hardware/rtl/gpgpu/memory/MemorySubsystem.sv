import gpu_pkg::*;
import MemorySubsystemPkg::*;

module MemorySubsystem #(
    parameter int unsigned N = 32
) (
    input logic clk,
    input logic rst_n,
    input logic abort,

    MemorySubsystemInterface.responder memory_if [N],

    output logic idle
);
    mem_req_t [N-1:0] req;
    logic [N-1:0] req_ready;
    logic [N-1:0] req_valid;
    logic [N-1:0] rsp_ready;

    word_t bram_rdata [N-1:0];
    logic [N-1:0] bram_cand;
    logic [N-1:0] bram_hold;
    logic [N-1:0] bram_accept;
    logic bram_busy;

    for (genvar i = 0; i < N; i++) begin : gen_reqs
        assign req[i] = memory_if[i].req;
        assign req_valid[i] = memory_if[i].req_valid;
        assign rsp_ready[i] = memory_if[i].rsp_ready;
        assign memory_if[i].req_ready = req_ready[i] & ~abort;
    end

    for (genvar i = 0; i < N; i++) begin : gen_port_controllers
        PortController portControllers (
            .clk(clk),
            .rst_n(rst_n),
            .rsp_ready(rsp_ready[i]),
            .req_valid(req_valid[i]),
            .req(req[i]),
            .bram_accept(bram_accept[i]),
            .bram_rdata(bram_rdata[i]),
            .ddr_accept('b0),
            // .is_idle(is_idle[i]),
            .req_ready(req_ready[i]),
            .rsp_valid(memory_if[i].rsp_valid),
            .rsp(memory_if[i].rsp),
            .bram_cand(bram_cand[i]),
            .bram_hold(bram_hold[i]),
            .ddr_cand()
        );
    end

    BRAMBackend #(
        .N(N)
    ) bramBackend (
        .clk(clk),
        .rst_n(rst_n),
        .req(req),
        .bram_cand(bram_cand),
        .bram_hold(bram_hold),
        .bram_accept(bram_accept),
        .bram_rdata(bram_rdata),
        .bram_busy(bram_busy)
    );

    assign idle = ~bram_busy;

endmodule
