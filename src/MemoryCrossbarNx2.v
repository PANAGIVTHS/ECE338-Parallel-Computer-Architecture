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

    // =========================================================================
    // N=2 Direct Wiring
    // Core 0 -> Memory Port A
    // Core 1 -> Memory Port B
    // =========================================================================

    // --- Port A (Core 0) ---
    assign o_ren_a  = i_req[0];
    assign o_wen_a  = i_req[0] ? i_wen[0] : 1'b0;
    assign o_addr_a = i_addr[ADDR_W-1:0];
    assign o_data_a = i_wdata[31:0];

    // --- Port B (Core 1) ---
    assign o_ren_b  = i_req[1];
    assign o_wen_b  = i_req[1] ? i_wen[1] : 1'b0;
    assign o_addr_b = i_addr[2*ADDR_W-1 : ADDR_W];
    assign o_data_b = i_wdata[63:32];

    // --- Core Responses ---
    // Immediate grant and valid since there's no multiplexing or stalling needed
    assign o_grant  = i_req;
    assign o_rvalid = i_req;
    assign o_rdata  = {i_out_b, i_out_a};

endmodule