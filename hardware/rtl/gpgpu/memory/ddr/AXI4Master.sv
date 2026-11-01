// AXIMasterPort — the only module connected to the DDR AXI4 bus.
//
// Drives the AR/AW command registers onto the bus with the fixed AXI
// constants, passes W/B/R between the bus and the rings, checks BID/RID and
// runs the timeout. After a fatal it stops issuing (AxVALID = WVALID = 0),
// sinks stray responses (BREADY = RREADY = 1) and hides every handshake from
// the rings, which then freeze. Recovery needs rst_n together with a reset of
// the SmartConnect/HP path.
module AXI4Master
    import AXI4FullPkg::*;
    import MemorySubsystemPkg::*;
    import DDRBackendPkg::*;
(
    input logic clk,
    input logic rst_n,

    AXI4FullInterface.master axi_if,

    // Read ring
    input cmd_t rd_cmd,                 // AR command register
    input logic r_ready,
    input logic rd_owed,                // a burst has sent its AR and still expects beats
    output logic ar_ready,
    output logic r_valid,
    output logic r_last,
    output beat_rdata_t r_data,         // to every PortController
    output axi_resp_t r_resp,

    // Write ring and assembler
    input cmd_t wr_cmd,                 // AW command register
    input logic w_valid,
    input logic w_last,
    input axi_data_t w_data,
    input axi_strb_t w_strb,
    input logic wr_owed,                // a B is owed
    output logic aw_ready,
    output logic w_ready,
    output logic b_valid,
    output axi_resp_t b_resp,

    // Sticky fatal from the DDRBackend register
    input logic i_fatal,
    output logic fatal,
    output mem_fatal_t fatal_code
);

    //& =============================================
    //& ADDRESS CHANNELS: command registers + constants
    //& =============================================
    always_comb begin
        axi_if.aw = '{
            id: AXI_ID,
            addr: wr_cmd.addr,
            len: wr_cmd.len,
            size: 3'(BEAT_LSB),
            burst: AXI_BURST_INCR,
            lock: 1'b0,
            cache: AXI_CACHE,
            prot: 3'b000,
            qos: 4'b0000
        };
        axi_if.ar = '{
            id: AXI_ID,
            addr: rd_cmd.addr,
            len: rd_cmd.len,
            size: 3'(BEAT_LSB),
            burst: AXI_BURST_INCR,
            lock: 1'b0,
            cache: AXI_CACHE,
            prot: 3'b000,
            qos: 4'b0000
        };
    end

    assign axi_if.aw_valid = wr_cmd.valid & ~i_fatal;
    assign axi_if.ar_valid = rd_cmd.valid & ~i_fatal;

    //& =============================================
    //& DATA AND RESPONSE CHANNELS
    //& =============================================
    assign axi_if.w = '{data: w_data, strb: w_strb, last: w_last};
    assign axi_if.w_valid = w_valid & ~i_fatal;
    assign axi_if.b_ready = 1'b1;                   // B goes straight into its slot
    assign axi_if.r_ready = r_ready | i_fatal;      // sink stray beats after a fatal

    // Handshakes are hidden from the rings after a fatal, so they freeze.
    assign aw_ready = axi_if.aw_ready & ~i_fatal;
    assign w_ready = axi_if.w_ready & ~i_fatal;
    assign ar_ready = axi_if.ar_ready & ~i_fatal;
    assign b_valid = axi_if.b_valid & ~i_fatal;
    assign r_valid = axi_if.r_valid & ~i_fatal;

    assign b_resp = axi_if.b.resp;
    assign r_last = axi_if.r.last;
    assign r_data = beat_rdata_t'(axi_if.r.data);
    assign r_resp = axi_if.r.resp;

    //& =============================================
    //& ID CHECKS
    //& =============================================
    logic wrong_id;
    assign wrong_id = (axi_if.b_valid & (axi_if.b.id != AXI_ID))
                    | (axi_if.r_valid & (axi_if.r.id != AXI_ID));

    //& =============================================
    //& TIMEOUT: consecutive cycles in which the slave owes progress and no
    //& handshake happens. An R beat held by our own back-pressure (RVALID
    //& high, RREADY low) is not waiting on the slave and does not count.
    //& =============================================
    logic any_fire, slave_owes, timeout;
    assign any_fire = (axi_if.aw_valid & axi_if.aw_ready) | (axi_if.w_valid & axi_if.w_ready)
                    | (axi_if.ar_valid & axi_if.ar_ready) | (axi_if.b_valid & axi_if.b_ready)
                    | (axi_if.r_valid & axi_if.r_ready);
    assign slave_owes = (axi_if.aw_valid & ~axi_if.aw_ready) | (axi_if.w_valid & ~axi_if.w_ready)
                      | (axi_if.ar_valid & ~axi_if.ar_ready)
                      | (wr_owed & ~axi_if.b_valid) | (rd_owed & ~axi_if.r_valid);

    if (AXI_TIMEOUT == 0) begin : g_no_timeout
        assign timeout = 1'b0;
    end else begin : g_timeout
        logic [$clog2(AXI_TIMEOUT + 1)-1:0] wait_cycles;

        always_ff @(posedge clk) begin
            if (~rst_n || any_fire || ~slave_owes) begin
                wait_cycles <= '0;
            end else if (~timeout) begin
                wait_cycles <= wait_cycles + 1'b1;
            end
        end

        // The AXI_TIMEOUT-th consecutive owed cycle without a handshake
        assign timeout = slave_owes & ~any_fire
                       & (wait_cycles == $bits(wait_cycles)'(AXI_TIMEOUT - 1));
    end

    //& =============================================
    //& FATAL REQUEST (the DDRBackend register makes it sticky)
    //& =============================================
    assign fatal = wrong_id | timeout;
    assign fatal_code = wrong_id ? FATAL_UNEXPECTED : timeout ? FATAL_TIMEOUT : FATAL_NONE;

endmodule
