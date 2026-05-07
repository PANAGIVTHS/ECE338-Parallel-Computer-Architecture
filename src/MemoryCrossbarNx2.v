module MemoryCrossbarNx2 #(
    parameter N = 8,             // Number of cores (can be anything >= 2)
    parameter DEPTH = 1024,
    parameter ADDR_W = $clog2(DEPTH)
)(
    input clk,
    input rst,

    input [N-1:0] i_req,
    input [N-1:0] i_wen,
    input [N*ADDR_W-1:0] i_addr, // Format: {coreN_addr, ..., core1_addr, core0_addr}
    input [N*32-1:0] i_wdata,    // Format: {coreN_wdata, ..., core1_wdata, core0_wdata}
    
    output [N-1:0] o_grant,
    output [N-1:0] o_rvalid,
    output [N*32-1:0] o_rdata,   // Format: {coreN_rdata, ..., core1_rdata, core0_rdata}

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

    //! Unpack the flattened inputs into Arrays
    reg [ADDR_W-1:0] addr_arr  [0:N-1];
    reg [31:0] wdata_arr [0:N-1];
    integer i;
    
    always @(*) begin
        for (i = 0; i < N; i = i + 1) begin
            addr_arr[i] = i_addr[i*ADDR_W +: ADDR_W];
            wdata_arr[i] = i_wdata[i*32 +: 32];
        end
    end

    // --- 2. Cascaded Priority Arbiters ---
    reg [$clog2(N)-1:0] sel_a, sel_b;
    reg en_a, en_b;
    reg [N-1:0] grant_a, grant_b;

    always @(*) begin
        en_a = 0; sel_a = 0; grant_a = 0;
        en_b = 0; sel_b = 0; grant_b = 0;

        // Arbiter A: Find the FIRST active request (Lowest Index = Highest Priority)
        for (i = 0; i < N; i = i + 1) begin
            if (i_req[i] && !en_a) begin
                en_a = 1;
                sel_a = i[$clog2(N)-1:0];
                grant_a[i] = 1'b1;
            end
        end

        // Arbiter B: Find the SECOND active request (Skip the one granted to A)
        for (i = 0; i < N; i = i + 1) begin
            if (i_req[i] && !grant_a[i] && !en_b) begin
                en_b = 1;
                sel_b = i[$clog2(N)-1:0];
                grant_b[i] = 1'b1;
            end
        end
    end

    assign o_grant = grant_a | grant_b;

    assign o_ren_a = en_a;
    assign o_wen_a = en_a ? i_wen[sel_a] : 1'b0;
    assign o_addr_a = addr_arr[sel_a];
    assign o_data_a = wdata_arr[sel_a];

    assign o_ren_b = en_b;
    assign o_wen_b = en_b ? i_wen[sel_b] : 1'b0;
    assign o_addr_b = addr_arr[sel_b];
    assign o_data_b = wdata_arr[sel_b];

    // --- 4. Read Response Routing (1 Cycle Delay) ---
    reg [$clog2(N)-1:0] sel_a_q, sel_b_q;
    reg read_val_a_q, read_val_b_q;

    always @(posedge clk) begin
        if (!rst) begin
            read_val_a_q <= 1'b0;
            read_val_b_q <= 1'b0;
        end else begin
            sel_a_q <= sel_a;
            sel_b_q <= sel_b;
            read_val_a_q <= en_a && !i_wen[sel_a];
            read_val_b_q <= en_b && !i_wen[sel_b];
        end
    end

    // --- 5. Pack outputs back to the Cores ---
    reg [N-1:0] rvalid_reg;
    always @(*) begin
        rvalid_reg = {N{1'b0}}; // Initialize all bits to 0
        if (read_val_a_q) rvalid_reg[sel_a_q] = 1'b1;
        if (read_val_b_q) rvalid_reg[sel_b_q] = 1'b1;
    end
    assign o_rvalid = rvalid_reg;

    // Use a generate block to dynamically pack the output data bus
    genvar g;
    generate
        for (g = 0; g < N; g = g + 1) begin : gen_rdata
            assign o_rdata[g*32 +: 32] = 
                (read_val_a_q && sel_a_q == g) ? i_out_a :
                (read_val_b_q && sel_b_q == g) ? i_out_b : 
                32'h00000000;
        end
    endgenerate

endmodule