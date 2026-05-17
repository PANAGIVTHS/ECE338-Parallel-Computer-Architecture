`timescale 1ns / 1ps

module MemoryCrossbarNx2 #(
    parameter N = 2,             
    parameter DEPTH = 1024,
    parameter ADDR_W = $clog2(DEPTH)
)(
    input clk,
    input rst,

    input [N-1:0] i_req,
    input [N-1:0] i_wen,
    input [N-1:0] i_amo,         
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
    //& AMO LOCK STATE MACHINE
    //& =============================================
    reg amo_active_a, amo_active_b;
    reg [ADDR_W-1:0] amo_addr_a, amo_addr_b;
    reg [31:0] amo_addend_a, amo_addend_b;

    reg mux_amo_a, mux_amo_b;

    always @(posedge clk) begin
        if (!rst) begin
            amo_active_a <= 1'b0;
            amo_active_b <= 1'b0;
        end else begin
            // Lock Port A for Cycle 2 Writeback
            if (winner_a_valid && mux_amo_a && !amo_active_a) begin
                amo_active_a <= 1'b1;
                amo_addr_a   <= mux_addr_a;
                amo_addend_a <= mux_data_a;
            end else begin
                amo_active_a <= 1'b0;
            end

            // Lock Port B for Cycle 2 Writeback
            if (winner_b_valid && mux_amo_b && !amo_active_b && !address_conflict) begin
                amo_active_b <= 1'b1;
                amo_addr_b   <= mux_addr_b;
                amo_addend_b <= mux_data_b;
            end else begin
                amo_active_b <= 1'b0;
            end
        end
    end

    //& =============================================
    //& PICK CORES TO SERVE
    //& =============================================
    reg [LOG2_N-1:0] winner_a_idx, winner_b_idx;
    reg winner_b_valid, winner_a_valid;
    wire [N-1:0] req_masked;
    integer j, i;

    always @(*) begin
        winner_a_valid = 1'b0;
        winner_a_idx = {LOG2_N{1'b0}};
        
        //! Only accept new requests if Port A is NOT locked by an AMO writeback
        if (!amo_active_a) begin
            for (i = N-1; i >= 0; i = i - 1) begin
                if (i_req[i]) begin
                    //! Enable second winner scan
                    winner_a_valid = 1'b1;
                    //! Find first winner

                    winner_a_idx = i[LOG2_N-1:0];
                end
            end
        end
    end

    //! Mask out first winner 
    assign req_masked = winner_a_valid ? (i_req & ~({{N-1{1'b0}}, 1'b1} << winner_a_idx)) : {N{1'b0}};

    always @(*) begin
        winner_b_valid = 1'b0;
        winner_b_idx   = {LOG2_N{1'b0}};
        
        //! Only accept new requests if Port B is NOT locked by an AMO writeback
        if (!amo_active_b) begin
            for (j = N-1; j >= 0; j = j - 1) begin
                if (req_masked[j]) begin
                    winner_b_valid = 1'b1;
                    winner_b_idx = j[LOG2_N-1:0];
                end
            end
        end
    end

    //& =============================================
    //& MUX THE WINNERS' SIGNALS
    //& =============================================
    reg [ADDR_W-1:0] mux_addr_a, mux_addr_b;
    reg [31:0] mux_data_a, mux_data_b;
    reg mux_wen_a, mux_wen_b;
    integer k;

    always @(*) begin
        mux_addr_a = {ADDR_W{1'b0}};
        mux_data_a = 32'h0;
        mux_wen_a = 1'b0;
        mux_amo_a = 1'b0;
        for (k = 0; k < N; k = k + 1) begin
            if (winner_a_valid && (winner_a_idx == k)) begin
                mux_addr_a = i_addr[k*ADDR_W +: ADDR_W];
                mux_data_a = i_wdata[k*32 +: 32];
                mux_wen_a  = i_wen[k];
                mux_amo_a  = i_amo[k];
            end
        end
    end

    always @(*) begin
        mux_addr_b = {ADDR_W{1'b0}};
        mux_data_b = 32'h0;
        mux_wen_b = 1'b0;
        mux_amo_b = 1'b0;
        for (k = 0; k < N; k = k + 1) begin
            if (winner_b_valid && (winner_b_idx == k)) begin
                mux_addr_b = i_addr[k*ADDR_W +: ADDR_W];
                mux_data_b = i_wdata[k*32 +: 32];
                mux_wen_b  = i_wen[k];
                mux_amo_b  = i_amo[k];
            end
        end
    end

    //& =============================================
    //& DRIVE OUTPUTS TO BRAM (WITH AMO OVERRIDES)
    //& =============================================
    assign o_addr_a = amo_active_a ? amo_addr_a : mux_addr_a;
    assign o_wen_a  = amo_active_a ? 1'b1 : mux_wen_a;
    assign o_ren_a  = amo_active_a ? 1'b1 : winner_a_valid;
    assign o_data_a = amo_active_a ? (i_out_a + amo_addend_a) : mux_data_a;

    assign o_addr_b = amo_active_b ? amo_addr_b : mux_addr_b;
    assign o_wen_b  = amo_active_b ? 1'b1 : (mux_wen_b && !address_conflict);
    assign o_ren_b  = amo_active_b ? 1'b1 : winner_b_valid;
    assign o_data_b = amo_active_b ? (i_out_b + amo_addend_b) : mux_data_b;

    //& =============================================
    //& OUTPUT GRANT AND VALID SIGNALS FOR LATCHING
    //& =============================================
    reg [N-1:0] grant_comb;
    always @(*) begin
        grant_comb = {N{1'b0}};
        if (winner_a_valid) grant_comb[winner_a_idx] = 1'b1;
        if (winner_b_valid && !address_conflict) grant_comb[winner_b_idx] = 1'b1;
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
                (port_b_active_r && (port_b_core_r == g)) ? i_out_b : 32'h0;
        end
    endgenerate

    //& =============================================
    //& ADDRESS CONFLICT DETECTION
    //& =============================================
    wire eff_wen_a = amo_active_a ? 1'b1 : mux_wen_a;
    wire eff_wen_b = amo_active_b ? 1'b1 : mux_wen_b;
    wire [ADDR_W-1:0] eff_addr_a = amo_active_a ? amo_addr_a : mux_addr_a;
    wire [ADDR_W-1:0] eff_addr_b = amo_active_b ? amo_addr_b : mux_addr_b;

    wire port_a_mutates = eff_wen_a | mux_amo_a | amo_active_a;
    wire port_b_mutates = eff_wen_b | mux_amo_b | amo_active_b;

    // A conflict occurs if both ports access the same address and at least one is changing it
    wire address_conflict = (winner_a_valid | amo_active_a) && 
                            (winner_b_valid | amo_active_b) && 
                            (eff_addr_a == eff_addr_b) && 
                            (port_a_mutates | port_b_mutates);

endmodule