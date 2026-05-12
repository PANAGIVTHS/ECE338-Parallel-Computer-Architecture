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

    // Lockstep assumption: If Core 0 requests, they all do.
    wire any_req = i_req[0]; 

    // N/2 Math
    localparam PAIRS = (N / 2);
    localparam MAX_IDX = (PAIRS > 0) ? (PAIRS - 1) : 0;

    // --- 1. Flatten arrays for clean routing ---
    wire [ADDR_W-1:0] addr_arr [0:N-1];
    wire [31:0] wdata_arr [0:N-1];
    
    genvar g;
    generate
        for (g = 0; g < N; g = g + 1) begin : unpack
            assign addr_arr[g]  = i_addr[g*ADDR_W +: ADDR_W];
            assign wdata_arr[g] = i_wdata[g*32 +: 32];
        end
    endgenerate

    // --- 2. N/2 Cycle Counter ---
    reg [$clog2(PAIRS > 0 ? PAIRS : 1):0] cycle_cnt;

    always @(posedge clk) begin
        if (!rst) cycle_cnt <= 0;
        else if (any_req) begin
            if (cycle_cnt == MAX_IDX) cycle_cnt <= 0;
            else cycle_cnt <= cycle_cnt + 1;
        end else cycle_cnt <= 0;
    end

    // --- 3. Route directly to BRAM ---
    wire [$clog2(N)-1:0] core_a = cycle_cnt * 2;
    wire [$clog2(N)-1:0] core_b = cycle_cnt * 2 + 1;

    assign o_ren_a  = any_req;
    assign o_wen_a  = any_req ? i_wen[core_a] : 1'b0;
    assign o_addr_a = addr_arr[core_a];
    assign o_data_a = wdata_arr[core_a];

    assign o_ren_b  = any_req;
    assign o_wen_b  = any_req ? i_wen[core_b] : 1'b0;
    assign o_addr_b = addr_arr[core_b];
    assign o_data_b = wdata_arr[core_b];

    // --- 4. Stall Control ---
    // Release the stall exactly on the cycle the LAST pair is requested
    assign o_grant = (any_req && cycle_cnt == MAX_IDX) ? {N{1'b1}} : {N{1'b0}};
    assign o_rvalid = o_grant;

    // --- 5. BRAM Pipeline Tracker ---
    reg [$clog2(PAIRS > 0 ? PAIRS : 1):0] read_pair_emerging;
    reg read_emerging_valid;

    always @(posedge clk) begin
        if (!rst) begin
            read_pair_emerging <= 0;
            read_emerging_valid <= 0;
        end else begin
            read_pair_emerging <= cycle_cnt;
            read_emerging_valid <= any_req && !i_wen[0];
        end
    end

    // Latch the earlier pairs, pass the final pair live combinatorially
    reg [31:0] rdata_latched [0:N-1];
    always @(posedge clk) begin
        if (read_emerging_valid) begin
            rdata_latched[read_pair_emerging * 2] <= i_out_a;
            rdata_latched[read_pair_emerging * 2 + 1] <= i_out_b;
        end
    end

    generate
        for (g = 0; g < N; g = g + 1) begin : pack_rdata
            assign o_rdata[g*32 +: 32] = 
                (g == MAX_IDX * 2)     ? i_out_a :
                (g == MAX_IDX * 2 + 1) ? i_out_b :
                                         rdata_latched[g];
        end
    endgenerate

endmodule