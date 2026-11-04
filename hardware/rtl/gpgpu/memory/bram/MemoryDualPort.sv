/**
 * True dual-port memory targeting Vivado BRAM.
 *
 * Simultaneous writes to the same address have undefined behavior.
 * Both ports use write-first behavior.
 */
module MemoryDualPort #(
    parameter int DEPTH = 1024,
    parameter INIT_FILE = "empty.mem"
)(
    input logic clk,

    MemoryInterface.slave memory_a,
    MemoryInterface.slave memory_b
);

    (* ram_style = "block" *) 
    logic [memory_a.DATA_WIDTH-1:0] data [0:DEPTH-1];

    localparam int EXPECTED_ADDR_WIDTH = (DEPTH > 1) ? $clog2(DEPTH) : 1;
    if (DEPTH <= 0) begin : g_depth_check
        $fatal(1, "Memory DEPTH must be positive");
    end

    if (memory_a.ADDR_WIDTH != EXPECTED_ADDR_WIDTH) begin : g_addr_a_check
        $fatal(1, "Port A address width mismatch: expected %0d, got %0d",
            EXPECTED_ADDR_WIDTH, memory_a.ADDR_WIDTH);
    end

    if (memory_b.ADDR_WIDTH != EXPECTED_ADDR_WIDTH) begin : g_addr_b_check
        $fatal(1, "Port B address width mismatch: expected %0d, got %0d",
            EXPECTED_ADDR_WIDTH, memory_b.ADDR_WIDTH);
    end

    if (memory_a.DATA_WIDTH != memory_b.DATA_WIDTH) begin : g_data_check
        $fatal(1, "Port data width mismatch: Port A = %0d, Port B = %0d",
            memory_a.DATA_WIDTH, memory_b.DATA_WIDTH);
    end

    initial begin
        if (INIT_FILE != "") begin
            $readmemh(INIT_FILE, data);
        end
    end
 
    // Port A
    always @(posedge clk) begin
        if (memory_a.ren) begin
            if (memory_a.wen) begin
                data[memory_a.addr] <= memory_a.wdata;
                memory_a.rdata <= memory_a.wdata;
            end else begin
                memory_a.rdata <= data[memory_a.addr];
            end
        end
    end

    // Port B
    always @(posedge clk) begin
        if (memory_b.ren) begin
            if (memory_b.wen) begin
                data[memory_b.addr] <= memory_b.wdata;
                memory_b.rdata <= memory_b.wdata;
            end else begin
                memory_b.rdata <= data[memory_b.addr];
            end
        end
    end

endmodule