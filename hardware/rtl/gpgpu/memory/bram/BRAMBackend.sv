module BRAMBackend 
    import MemorySubsystemPkg::*;
    import gpu_pkg::*;
#(
    parameter N = 32,             // Number of requests 
    localparam IDX_W = N > 1 ? $clog2(N) : 1
) (
    input clk,
    input rst_n,

    //! Requests and ready
    input mem_req_t [N-1:0] req,
    input logic [N-1:0] bram_cand,
    input logic [N-1:0] bram_hold,

    //! Responses
    output logic [N-1:0] bram_accept,
    output word_t bram_rdata [N-1:0],
    output logic bram_busy
);

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
        assign hold[i] = busy[i] & ~bram_hold[owners[i]];
    end

    assign bram_busy = busy[0] | busy[1];

    //& =============================================
    //& PICK REQUESTS TO SERVE
    //& =============================================
    logic [1:0][N-1:0] win_oh; //one-hot
    logic [1:0] win_vld;
    logic [1:0][IDX_W-1:0] win_idx;

    ArbiterMLowest #(
        .N(N),
        .M(2)
    ) arbiterMLowest (
        .req(bram_cand),
        .grant(),
        .win_oh(win_oh),
        .win_vld(win_vld),
        .win_idx(win_idx)
    );

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
    assign bram_accept = (win_issue[0] ? win_oh[0] : '0) | (win_issue[1] ? win_oh[1] : '0);

    MemoryInterface #(
        .ADDR_WIDTH(DMEM_AW)
    ) port_a();

    MemoryInterface #(
        .ADDR_WIDTH(DMEM_AW)
    ) port_b();

    MemoryDualPort #(
        .DEPTH(DMEM_ENTRIES)
    ) dataMemory (
        .clk(clk),
        .memory_a(port_a.slave),
        .memory_b(port_b.slave)
    );

    // Port B is used only if 2 winners are selected or portA is not available
    wire portA_valid = available[0] & win_issue[0];
    wire [IDX_W-1:0] portA_idx = win_idx[0];
    wire portA_load = portA_valid & ~req[portA_idx].write;
    // Port B is used only if 2 winners are selected or portA is not available
    wire portB_win1 = ~available[0] & available[1] & win_issue[0];
    wire portB_win2 = available[0] & available[1] & win_issue[1];
    wire portB_valid = portB_win1 | portB_win2;
    wire [IDX_W-1:0] portB_idx = portB_win1 ? win_idx[0] : win_idx[1];
    wire portB_load = portB_valid & ~req[portB_idx].write;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            busy[0] <= 1'b0;
            busy[1] <= 1'b0;
        end else begin
            if (portA_load) begin 
                busy[0] <= 1'b1; 
                owners[0] <= portA_idx; 
            end else if (busy[0] & bram_hold[owners[0]]) 
                busy[0] <= 1'b0;
            
            if (portB_load) begin 
                busy[1] <= 1'b1;
                owners[1] <= portB_idx; 
            end else if (busy[1] & bram_hold[owners[1]]) 
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
    for (genvar g = 0; g < N; g = g + 1) begin : routing
        always_comb begin
            if (busy[0] && owners[0] == g[IDX_W-1:0]) begin
                bram_rdata[g] = port_a.rdata;
            end else if (busy[1] && owners[1] == g[IDX_W-1:0]) begin
                bram_rdata[g] = port_b.rdata;
            end else begin
                bram_rdata[g] = '0;
            end
        end
    end

endmodule
