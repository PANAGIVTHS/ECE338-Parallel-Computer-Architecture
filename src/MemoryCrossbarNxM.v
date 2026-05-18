`timescale 1ns/1ps

module MemoryCrossbarNxM #(
    parameter N = 2,           // Number of Cores
    parameter M = 8,           // Number of Memory Banks
    parameter ADDR_W = 32,     // Width of memory address
    parameter BANK_BITS = 3    // log2(M) - Number of bits used for interleaving
)(
    input  wire                 i_clk,
    input  wire                 i_rst,

    // ==========================================
    // Core-Facing Interface (Flat Buses)
    // ==========================================
    input  wire [N-1:0]         i_req,
    input  wire [N-1:0]         i_wen,
    input  wire [N-1:0]         i_amo,
    input  wire [N*ADDR_W-1:0]  i_addr,
    input  wire [N*32-1:0]      i_wdata,
 
    output wire [N-1:0]         o_grant,
    output wire [N-1:0]         o_rvalid,
    output wire [N*32-1:0]      o_rdata,

    // ==========================================
    // Memory-Facing Interface (Flat Buses for Banks)
    // ==========================================
    output wire [M*ADDR_W-1:0]  o_bank_addr,
    output wire [M-1:0]         o_bank_ren,
    output wire [M-1:0]         o_bank_wen,
    output wire [M*32-1:0]      o_bank_wdata,
    input  wire [M*32-1:0]      i_bank_rdata
);
    // -------------------------------------------------------------------------
    // 1. Unpack Flat Buses into 2D Arrays for Logic Readability
    // -------------------------------------------------------------------------
    wire [ADDR_W-1:0] core_addr  [0:N-1];
    wire [31:0] core_wdata [0:N-1];
    wire [BANK_BITS-1:0] target_bank [0:N-1];

    genvar g;
    generate
        for (g = 0; g < N; g = g + 1) begin : gen_unpack_core
            assign core_addr[g]  = i_addr[(g+1)*ADDR_W - 1 : g*ADDR_W];
            assign core_wdata[g] = i_wdata[(g+1)*32 - 1 : g*32];
            assign target_bank[g] = core_addr[g][BANK_BITS-1:0];
        end
    endgenerate

    wire [31:0] bank_rdata_unpacked [0:M-1];
    generate
        for (g = 0; g < M; g = g + 1) begin : gen_unpack_memory
            assign bank_rdata_unpacked[g] = i_bank_rdata[(g+1)*32 - 1 : g*32];
        end
    endgenerate

    // -------------------------------------------------------------------------
    // 2. Combinational Arbitration (Fixed Priority: Core 0 > Core N)
    // -------------------------------------------------------------------------
    reg amo_active [0:M-1];
    reg [ADDR_W-1:0] amo_addr [0:M-1];
    reg [31:0] amo_addend [0:M-1];
    reg bank_active [0:M-1];
    reg [31:0] bank_winner [0:M-1]; 
    
    reg [ADDR_W-1:0] r_bank_addr  [0:M-1];
    reg [31:0] r_bank_wdata [0:M-1];
    reg r_bank_ren [0:M-1];
    reg r_bank_wen [0:M-1];
    reg [N-1:0] r_core_grant;

    integer i, j;
    always @(*) begin
        // A. Initialize defaults
        for (j = 0; j < M; j = j + 1) begin
            bank_active[j]  = 1'b0;
            bank_winner[j]  = 0;
            
            // If AMO is active, crossbar hijacks the bank to write the math result
            r_bank_addr[j]  = amo_active[j] ? amo_addr[j] : 0;
            r_bank_wdata[j] = amo_active[j] ? (bank_rdata_unpacked[j] + amo_addend[j]) : 0;
            r_bank_ren[j]   = amo_active[j] ? 1'b1 : 1'b0;
            r_bank_wen[j]   = amo_active[j] ? 1'b1 : 1'b0;
        end
        for (i = 0; i < N; i = i + 1) begin
            r_core_grant[i] = 1'b0;
        end

        // B. Determine bank winners
        for (j = 0; j < M; j = j + 1) begin
            // Only accept new requests if Bank is NOT locked by an AMO writeback
            if (!amo_active[j]) begin
                // Loop downwards so lowest core index (i=0) overwrites and wins priority
                for (i = N - 1; i >= 0; i = i - 1) begin
                    if (i_req[i] && (target_bank[i] == j)) begin
                        bank_active[j] = 1'b1;
                        bank_winner[j] = i;
                    end
                end
            end
        end

        // C. Route the winning core's signals to the memory bank
        for (j = 0; j < M; j = j + 1) begin
            if (bank_active[j] && !amo_active[j]) begin
                i = bank_winner[j]; // The core ID that won this bank
                r_core_grant[i] = 1'b1;
                r_bank_addr[j]  = core_addr[i];
                r_bank_wdata[j] = core_wdata[i];
                r_bank_wen[j]   = i_wen[i];
                r_bank_ren[j]   = 1'b1;
            end
        end
    end

    // D. AMO Lock State Machine Update
    always @(posedge i_clk) begin
        if (!i_rst) begin
            for (i = 0; i < M; i = i + 1) begin
                amo_active[i] <= 1'b0;
                amo_addr[i]   <= 0;
                amo_addend[i] <= 0;
            end
        end else begin
            for (j = 0; j < M; j = j + 1) begin
                // Lock Bank for Cycle 2 Writeback
                if (bank_active[j] && !amo_active[j] && i_amo[bank_winner[j]]) begin
                    amo_active[j] <= 1'b1;
                    amo_addr[j]   <= core_addr[bank_winner[j]];
                    amo_addend[j] <= core_wdata[bank_winner[j]];
                end else begin
                    amo_active[j] <= 1'b0;
                end
            end
        end
    end

    assign o_grant = r_core_grant;

    // -------------------------------------------------------------------------
    // 3. Read Data Tracking (1-Cycle Delay)
    // -------------------------------------------------------------------------
    reg [N-1:0]         rvalid_q;
    reg [BANK_BITS-1:0] saved_target_bank [0:N-1];

    always @(posedge i_clk) begin
        if (!i_rst) begin
            rvalid_q <= {N{1'b0}};
            for (i = 0; i < N; i = i + 1) begin
                saved_target_bank[i] <= 0;
            end
        end else begin
            for (i = 0; i < N; i = i + 1) begin
                // A core expects valid read data if it was granted a non-write request (or AMO)
                if (r_core_grant[i] && (!i_wen[i] || i_amo[i])) begin
                    rvalid_q[i] <= 1'b1;
                    saved_target_bank[i] <= target_bank[i];
                end else begin
                    rvalid_q[i] <= 1'b0;
                end
            end
        end
    end

    assign o_rvalid = rvalid_q;

    // -------------------------------------------------------------------------
    // 4. Steer Read Data Back to Cores & Pack Output Buses
    // -------------------------------------------------------------------------
    reg [31:0] core_rdata [0:N-1];
    always @(*) begin
        for (i = 0; i < N; i = i + 1) begin
            if (rvalid_q[i]) begin
                // Route the data from the bank this core successfully targeted last cycle
                core_rdata[i] = bank_rdata_unpacked[ saved_target_bank[i] ];
            end else begin
                core_rdata[i] = 32'h0; // Default to zero if no read was active
            end
        end
    end

    generate
        for (g = 0; g < M; g = g + 1) begin : gen_pack_memory
            assign o_bank_addr[(g+1)*ADDR_W - 1 : g*ADDR_W] = r_bank_addr[g];
            assign o_bank_wdata[(g+1)*32 - 1 : g*32]        = r_bank_wdata[g];
            assign o_bank_ren[g]                            = r_bank_ren[g];
            assign o_bank_wen[g]                            = r_bank_wen[g];
        end

        for (g = 0; g < N; g = g + 1) begin : gen_pack_core
            assign o_rdata[(g+1)*32 - 1 : g*32]             = core_rdata[g];
        end
    endgenerate

endmodule