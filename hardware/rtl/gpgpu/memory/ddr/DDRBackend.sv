module DDRBackend 
    import gpu_pkg::*;
    import AXI4FullPkg::*;
    import MemorySubsystemPkg::*;
    import DDRBackendPkg::*;
#(
    parameter int unsigned NUM_REQ = 32,
    localparam IDX_W = NUM_REQ > 1 ? $clog2(NUM_REQ) : 1
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
    logic [NUM_REQ-1:0] wr_take;

    for (genvar i = 0; i < NUM_REQ; i++) begin: ddr_expand
        assign idx[i] = ddr_if[i].idx;
        assign wr_take[i] = ddr_if[i].wr_take;
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
    assign rd_ring_free = 1'b0; // TODO: remove when read ring is impemented (Currently hangs read instrutions)

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

    for (genvar i = 0; i < NUM_REQ; i++) begin: wr_member_expand
        assign wr_members[i] = ddr_if[i].wr_member;
    end

    DDRWriteRing #(
        .NUM_REQ(NUM_REQ)
     ) ddrWriteRing (
        .clk          (clk),
        .rst_n        (rst_n),
        // AXI channels
        .aw_ready     (aw_ready),
        .aw_cmd       (aw_cmd),
        .w_beat       (w_beat),
        .w_slot       (w_slot),
        .w_bdone      (w_bdone),
        .w_bresp      (w_bresp),
        // Group formation
        .push_wr      (push_wr),
        .group_address(group_address),
        .first_beat   (first_beat),
        .last_beat    (last_beat),
        // DDR interface from requesters
        .wr_members   (wr_members),
        .idx          (idx),
        .wr_take      (wr_take),
        // Ring state
        .free         (free),
        .alloc        (alloc),
        .busy         (busy),
        .fatal        (fatal),
        .fatal_code   (fatal_code),
    );
    
    //! Note: Remember to make o_fatal along with o_fatal_code sticky on a register

endmodule
