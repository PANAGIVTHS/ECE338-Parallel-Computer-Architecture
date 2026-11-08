module BRAMBackend 
    import MemorySubsystemPkg::*;
    import gpu_pkg::*;
#(
    parameter int unsigned NUM_REQ = 32, // Number of requests
    parameter BRAM_INIT = "",
    localparam IDX_W = NUM_REQ > 1 ? $clog2(NUM_REQ) : 1
) (
    input clk,
    input rst_n,

    input mem_req_t [NUM_REQ-1:0] req,
    BRAMBackendInterface.responder bram_if [NUM_REQ],

    output logic o_busy
);
    // Two stages, so that picking requests and issuing them to the BRAM are
    // never in the same cycle. Each cycle picks the two lowest-index
    // candidates outside the two being issued, and the next cycle issues
    // them: still two accesses per cycle, each accepted one cycle after it
    // becomes a candidate. A pick that cannot issue (its port still holds
    // data, or it writes the other pick's word) is issued first next cycle,
    // so accesses to one word still reach the BRAM from the lowest index up.

    //& =============================================
    //& PORT EXPANSION
    //& =============================================
    logic [NUM_REQ-1:0] cand, pick, take;
    for (genvar i = 0; i < NUM_REQ; i++) begin : cand_expand
        assign cand[i] = bram_if[i].cand;
        assign pick[i] = bram_if[i].pick;
        assign take[i] = bram_if[i].take;
    end

    //& =============================================
    //& BUSY PORT MANAGING
    //& =============================================
    // current port owners
    logic [1:0][IDX_W-1:0] owners; 
    // busy ports (port used for read on the previous cycle)
    logic [1:0] busy; 
    // port contains previous requested result but requester not ready
    logic [1:0] hold;
    // port contains previous requested result but can be reused on the next cycle (since requester will claim it)
    wire [1:0] available = ~hold;

    for (genvar i = 0; i < 2; i++) begin : hold_ports
        assign hold[i] = busy[i] & ~take[owners[i]];
    end

    assign o_busy = busy[0] | busy[1];

    //& =============================================
    //& PICK REQUESTS TO SERVE NEXT CYCLE
    //& =============================================
    // The picks being issued: one-hot, zero when there is none
    logic [1:0][NUM_REQ-1:0] win_oh;
    logic [1:0][IDX_W-1:0] win_idx;
    logic [1:0][NUM_REQ-1:0] next_oh;
    logic [1:0][IDX_W-1:0] next_idx;

    ArbiterMLowest #(
        .N(NUM_REQ),
        .M(2)
    ) arbiterMLowest (
        .req(pick & ~(win_oh[0] | win_oh[1])),
        .grant(),
        .win_oh(next_oh),
        .win_vld(),
        .win_idx(next_idx)
    );

    // A pick is issued only while it is still a candidate
    logic [1:0] win_vld;
    for (genvar k = 0; k < 2; k++) begin : still_cand
        assign win_vld[k] = |(win_oh[k] & cand);
    end

    //& =============================================
    //& WRITE COLLISION DETECTION
    //& =============================================
    wire same_word = (req[win_idx[0]].addr[DMEM_AW+1:2] == req[win_idx[1]].addr[DMEM_AW+1:2]);
    wire conflict  = win_vld[0] & win_vld[1] & same_word & (req[win_idx[0]].write | req[win_idx[1]].write);

    //& =============================================
    //& MUX THE WINNERS' SIGNALS INTO THE BRAM
    //& =============================================
    logic [1:0] win_issue;
    assign win_issue[0] = (available[0] | available[1]) & win_vld[0];
    assign win_issue[1] = (available[0] & available[1]) & win_vld[1] & ~conflict;

    // Picks left behind go first next cycle. Pick 0 is left behind only
    // when no port is free, and then pick 1 is too: both are kept.
    wire keep_both = win_vld[0] & ~win_issue[0];
    wire keep_one = win_vld[1] & ~win_issue[1];

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            win_oh <= '0;
        end else if (keep_both) begin
            win_oh <= win_oh;
        end else if (keep_one) begin
            win_oh <= {next_oh[0], win_oh[1]};
        end else begin
            win_oh <= next_oh;
        end
    end

    // Read only while its pick is set
    always_ff @(posedge clk) begin
        if (keep_both) begin
            win_idx <= win_idx;
        end else if (keep_one) begin
            win_idx <= {next_idx[0], win_idx[1]};
        end else begin
            win_idx <= next_idx;
        end
    end

    for (genvar i = 0; i < NUM_REQ; i++) begin : accept_join
        assign bram_if[i].accept = (win_issue[0] & win_oh[0][i]) | (win_issue[1] & win_oh[1][i]);
    end

    MemoryInterface #(
        .ADDR_WIDTH(DMEM_AW)
    ) port_a();

    MemoryInterface #(
        .ADDR_WIDTH(DMEM_AW)
    ) port_b();

    MemoryDualPort #(
        .DEPTH(DMEM_ENTRIES),
        .INIT_FILE(BRAM_INIT)
    ) dataMemory (
        .clk(clk),
        .memory_a(port_a.slave),
        .memory_b(port_b.slave)
    );

    // Copies for the read data: requester g reads copy g*COPIES/NUM_REQ, so
    // no BRAM output has to reach every requester across the device. They
    // take dataMemory's accesses, so they hold its words; simulation, whose
    // benches access dataMemory, reads it for every copy. dont_touch keeps
    // synthesis from merging them.
    localparam int unsigned COPIES = NUM_REQ < 4 ? NUM_REQ : 4;
    word_t copy_rdata_a [COPIES], copy_rdata_b [COPIES];
    assign copy_rdata_a[0] = port_a.rdata;
    assign copy_rdata_b[0] = port_b.rdata;

    for (genvar k = 1; k < COPIES; k++) begin : g_copy
`ifdef SYNTHESIS
        MemoryInterface #(.ADDR_WIDTH(DMEM_AW)) copy_a ();
        MemoryInterface #(.ADDR_WIDTH(DMEM_AW)) copy_b ();
        assign copy_a.addr = port_a.addr;
        assign copy_a.wdata = port_a.wdata;
        assign copy_a.ren = port_a.ren;
        assign copy_a.wen = port_a.wen;
        assign copy_b.addr = port_b.addr;
        assign copy_b.wdata = port_b.wdata;
        assign copy_b.ren = port_b.ren;
        assign copy_b.wen = port_b.wen;
        assign copy_rdata_a[k] = copy_a.rdata;
        assign copy_rdata_b[k] = copy_b.rdata;

        (* dont_touch = "true" *)
        MemoryDualPort #(
            .DEPTH(DMEM_ENTRIES),
            .INIT_FILE(BRAM_INIT)
        ) dataMemory (
            .clk(clk),
            .memory_a(copy_a.slave),
            .memory_b(copy_b.slave)
        );
`else
        assign copy_rdata_a[k] = port_a.rdata;
        assign copy_rdata_b[k] = port_b.rdata;
`endif
    end

    // Port B is used only if 2 winners are selected or portA is not available
    wire portA_valid = available[0] & win_issue[0];
    wire [IDX_W-1:0] portA_idx = win_idx[0];
    wire portA_load = portA_valid & ~req[portA_idx].write;
    // Port B is used only if 2 winners are selected or portA is not available
    wire portB_win1 = ~available[0] & available[1] & win_issue[0];
    wire portB_win2 = available[0] & available[1] & win_issue[1];
    wire portB_valid = portB_win1 | portB_win2;
    // Port B serves pick 0 only while port A holds data: the BRAM address
    // does not wait for the issue decision
    wire [IDX_W-1:0] portB_idx = available[0] ? win_idx[1] : win_idx[0];
    wire portB_load = portB_valid & ~req[portB_idx].write;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            busy[0] <= 1'b0;
            busy[1] <= 1'b0;
        end else begin
            if (portA_load) begin 
                busy[0] <= 1'b1; 
                owners[0] <= portA_idx; 
            end else if (busy[0] & take[owners[0]]) 
                busy[0] <= 1'b0;
            
            if (portB_load) begin 
                busy[1] <= 1'b1;
                owners[1] <= portB_idx; 
            end else if (busy[1] & take[owners[1]]) 
                busy[1] <= 1'b0;
        end
    end

    assign port_a.ren = portA_valid;
    assign port_a.wen = req[portA_idx].write;
    assign port_a.addr = req[portA_idx].addr[DMEM_AW+1:2];
    assign port_a.wdata = req[portA_idx].wdata;

    assign port_b.ren = portB_valid;
    assign port_b.wen = req[portB_idx].write;
    assign port_b.addr = req[portB_idx].addr[DMEM_AW+1:2];
    assign port_b.wdata = req[portB_idx].wdata;

    //& =============================================
    //& READ-DATA ROUTING
    //& =============================================

    //! Steer the delayed BRAM output back to the specific requester that requested it
    for (genvar g = 0; g < NUM_REQ; g = g + 1) begin : routing
        always_comb begin
            if (busy[0] && owners[0] == g[IDX_W-1:0]) begin
                bram_if[g].rdata = copy_rdata_a[g * COPIES / NUM_REQ];
            end else if (busy[1] && owners[1] == g[IDX_W-1:0]) begin
                bram_if[g].rdata = copy_rdata_b[g * COPIES / NUM_REQ];
            end else begin
                bram_if[g].rdata = '0;
            end
        end
    end

endmodule
