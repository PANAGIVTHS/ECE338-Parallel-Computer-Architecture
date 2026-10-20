`timescale 1ns / 1ps

module MemoryCrossbarNx2 #(
    parameter N = 2,             // Number of cores 
    parameter DEPTH = 1024,
    parameter ADDR_W = $clog2(DEPTH)
)(
    input clk,
    input rst,

    //! Core Requests
    MemoryInterface.arbiter cores[N],

    //! Memory Ports
    MemoryInterface.master memory_a, memory_b
);

    localparam LOG2_N = $clog2(N);
    logic collision_w;
    logic [N-1:0] i_req, i_wen;
    logic [N*ADDR_W-1:0] i_addr;
    logic [N*32-1:0] i_wdata, o_rdata;

    for (genvar c = 0; c < N; c++) begin : gen_cores
        assign i_req[c] = cores[c].ren;
        assign i_wen[c] = cores[c].wen;
        assign i_addr[c*ADDR_W +: ADDR_W] = cores[c].addr;
        assign i_wdata[c*32 +: 32] = cores[c].wdata;
        assign cores[c].grant = grant_comb[c];
        assign cores[c].rvalid = grant_comb[c];
        assign cores[c].rdata = o_rdata[c*32 +: 32];
    end

    //& =============================================
    //& PICK CORES TO SERVE
    //& =============================================

    //! Find index closest to LSB which isnt zero
    logic [LOG2_N-1:0] winner_a_idx, winner_b_idx;
    logic winner_b_valid, winner_a_valid;
    logic [N-1:0] req_masked;
    integer j, i;

    always_comb begin
        winner_a_valid = 1'b0;
        winner_a_idx = {LOG2_N{1'b0}};
        for (i = N-1; i >= 0; i = i - 1) begin
            if (i_req[i]) begin
                //! Enable second winner scan
                winner_a_valid = 1'b1;
                //! Find first winner
                winner_a_idx = i[LOG2_N-1:0];
            end
        end
    end

    //! Mask out first winner 
    assign req_masked = winner_a_valid ? (i_req & ~({{N-1{1'b0}}, 1'b1} << winner_a_idx)) : {N{1'b0}};

    always_comb begin
        winner_b_valid = 1'b0;
        winner_b_idx   = {LOG2_N{1'b0}};
        for (j = N-1; j >= 0; j = j - 1) begin
            if (req_masked[j]) begin
                winner_b_valid = 1'b1;
                winner_b_idx = j[LOG2_N-1:0];
            end
        end
    end

    //& =============================================
    //& MUX THE WINNERS' SIGNALS INTO THE BRAM
    //& =============================================
    logic [ADDR_W-1:0] mux_addr_a, mux_addr_b;
    logic [31:0] mux_data_a, mux_data_b;
    logic mux_wen_a, mux_wen_b;

    always_comb begin
        mux_addr_a = {ADDR_W{1'b0}};
        mux_data_a = 32'h0;
        mux_wen_a = 1'b0;
        for (int k = 0; k < N; k = k + 1) begin
            if (winner_a_valid && (winner_a_idx == k)) begin
                mux_addr_a = i_addr[k*ADDR_W +: ADDR_W];
                mux_data_a = i_wdata[k*32 +: 32];
                mux_wen_a = i_wen[k];
            end
        end
    end

    always_comb begin
        mux_addr_b = {ADDR_W{1'b0}};
        mux_data_b = 32'h0;
        mux_wen_b = 1'b0;
        for (int k = 0; k < N; k = k + 1) begin
            if (winner_b_valid && (winner_b_idx == k)) begin
                mux_addr_b = i_addr[k*ADDR_W +: ADDR_W];
                mux_data_b = i_wdata[k*32 +: 32];
                mux_wen_b = i_wen[k];
            end
        end
    end

    //! Drive outputs
    assign memory_a.addr = mux_addr_a;
    assign memory_a.wen = mux_wen_a;
    assign memory_a.ren = winner_a_valid;
    assign memory_a.wdata = mux_data_a;

    assign memory_b.addr = mux_addr_b;
    assign memory_b.wen = mux_wen_b && !collision_w;
    assign memory_b.ren = winner_b_valid;
    assign memory_b.wdata = mux_data_b;

    //& =============================================
    //& OUTPUT GRANT AND VALID SIGNALS FOR LATCHING
    //& =============================================
    logic [N-1:0] grant_comb;
    always_comb begin
        grant_comb = {N{1'b0}};
        if (winner_a_valid) grant_comb[winner_a_idx] = 1'b1;
        if (winner_b_valid && !collision_w) grant_comb[winner_b_idx] = 1'b1;
    end


    //& =============================================
    //& READ-DATA ROUTING (1-CYCLE PIPELINE DELAY)
    //& =============================================
    logic [LOG2_N-1:0] port_a_core_r, port_b_core_r;
    logic port_a_active_r, port_b_active_r;

    always_ff @(posedge clk) begin
        if (!rst) begin
            port_a_active_r <= 1'b0;
            port_b_active_r <= 1'b0;
            port_a_core_r <= {LOG2_N{1'b0}};
            port_b_core_r <= {LOG2_N{1'b0}};
        end else begin
            port_a_active_r <= winner_a_valid;
            port_b_active_r <= winner_b_valid;
            if (winner_a_valid) port_a_core_r <= winner_a_idx;
            if (winner_b_valid) port_b_core_r <= winner_b_idx;
        end
    end

    //! Steer the delayed BRAM output back to the specific core that requested it
    genvar g;
    generate
        for (g = 0; g < N; g = g + 1) begin
            assign o_rdata[g*32 +: 32] = 
                (port_a_active_r && (port_a_core_r == g)) ? memory_a.rdata :
                (port_b_active_r && (port_b_core_r == g)) ? memory_b.rdata : 
                32'h0;
        end
    endgenerate

    //& =============================================
    //& WRITE COLLISION DETECTION
    //& =============================================
    logic [ADDR_W-1:0] collision_addr_w;

    assign collision_w = winner_a_valid && winner_b_valid && mux_wen_a && mux_wen_b && (mux_addr_a == mux_addr_b);
    assign collision_addr_w = mux_addr_a;

    // always_ff @(posedge clk) begin
    //     if (collision_w)
    //         $display("[Crossbar] @%0t WARNING: Memory corruption on write address 0x%0h",
    //                 $time, collision_addr_w);
    // end
endmodule