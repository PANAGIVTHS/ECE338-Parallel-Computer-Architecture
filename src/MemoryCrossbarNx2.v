`timescale 1ns / 1ps

module MemoryCrossbarNx2 #(
    parameter N = 2,             // Number of cores 
    parameter DEPTH = 1024,
    parameter ADDR_W = $clog2(DEPTH)
)(
    input clk,
    input rst,

    input [N-1:0] i_req,
    input [N-1:0] i_wen,
    input [N*ADDR_W-1:0] i_addr, 
    input [N*32-1:0] i_wdata,    
    
    output [N-1:0] o_grant,
    output [N-1:0] o_rvalid,
    output [N*32-1:0] o_rdata,   

    //! Memory Port A
    output [ADDR_W-1:0] o_addr_a,
    output o_ren_a,  
    output o_wen_a,
    output [31:0] o_data_a,
    input [31:0] i_out_a,  

    //! Memory Port B
    output [ADDR_W-1:0] o_addr_b,
    output o_ren_b,  
    output o_wen_b,
    output [31:0] o_data_b,
    input [31:0] i_out_b 
);

    localparam LOG2_N = $clog2(N);

    //& =============================================
    //& PICK CORES TO SERVE
    //& =============================================

    //! Find index closest to LSB which isnt zero
    reg [LOG2_N-1:0] winner_a_idx, winner_b_idx;
    reg winner_b_valid, winner_a_valid;
    wire [N-1:0] req_masked;
    integer j, i;

    always @(*) begin
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

    always @(*) begin
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
    reg [ADDR_W-1:0] mux_addr_a, mux_addr_b;
    reg [31:0] mux_data_a, mux_data_b;
    reg mux_wen_a, mux_wen_b;
    integer k;

    always @(*) begin
        mux_addr_a = {ADDR_W{1'b0}};
        mux_data_a = 32'h0;
        mux_wen_a = 1'b0;
        for (k = 0; k < N; k = k + 1) begin
            if (winner_a_valid && (winner_a_idx == k)) begin
                mux_addr_a = i_addr[k*ADDR_W +: ADDR_W];
                mux_data_a = i_wdata[k*32 +: 32];
                mux_wen_a = i_wen[k];
            end
        end
    end

    always @(*) begin
        mux_addr_b = {ADDR_W{1'b0}};
        mux_data_b = 32'h0;
        mux_wen_b = 1'b0;
        for (k = 0; k < N; k = k + 1) begin
            if (winner_b_valid && (winner_b_idx == k)) begin
                mux_addr_b = i_addr[k*ADDR_W +: ADDR_W];
                mux_data_b = i_wdata[k*32 +: 32];
                mux_wen_b = i_wen[k];
            end
        end
    end

    //! Drive outputs
    assign o_addr_a = mux_addr_a;
    assign o_wen_a = mux_wen_a;
    assign o_ren_a = winner_a_valid;
    assign o_data_a = mux_data_a;

    assign o_addr_b = mux_addr_b;
    assign o_wen_b = mux_wen_b;
    assign o_ren_b = winner_b_valid;
    assign o_data_b = mux_data_b;

    //& =============================================
    //& OUTPUT GRANT AND VALID SIGNALS FOR LATCHING
    //& =============================================
    reg [N-1:0] grant_comb;
    always @(*) begin
        grant_comb = {N{1'b0}};
        if (winner_a_valid) grant_comb[winner_a_idx] = 1'b1;
        if (winner_b_valid) grant_comb[winner_b_idx] = 1'b1;
    end

    assign o_grant = grant_comb;
    assign o_rvalid = grant_comb;

    //& =============================================
    //& READ-DATA ROUTING (1-CYCLE PIPELINE DELAY)
    //& =============================================
    reg [LOG2_N-1:0] port_a_core_r, port_b_core_r;
    reg port_a_active_r, port_b_active_r;

    always @(posedge clk) begin
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
                (port_a_active_r && (port_a_core_r == g)) ? i_out_a :
                (port_b_active_r && (port_b_core_r == g)) ? i_out_b : 
                32'h0;
        end
    endgenerate

    //& =============================================
    //& WRITE COLLISION DETECTION
    //& =============================================
    wire collision_w;
    wire [ADDR_W-1:0] collision_addr_w;

    assign collision_w = winner_a_valid && winner_b_valid && mux_wen_a && mux_wen_b && (mux_addr_a == mux_addr_b);
    assign collision_addr_w = mux_addr_a;

    always @(posedge clk) begin
        if (collision_w)
            $display("[MemoryCrossbarNx2] @%0t WARNING: Possible corruption on memory write request at address 0x%0h",
                    $time, collision_addr_w);
    end
endmodule