// Word-addressed memory signal bundle. ren enables reads AND writes;
// wen selects a write when ren is asserted. BRAM targets register rdata on
// clk and hold it when disabled; arbiters preserve their existing routing.
// Arbitration grants remain separate. The interface itself adds no timing
// logic and does not imply a variable-latency/DDR transaction handshake.
interface MemoryInterface #(
    parameter int unsigned ADDR_WIDTH = 32,
    parameter int unsigned DATA_WIDTH = 32
);
    logic [ADDR_WIDTH-1:0] addr;
    logic ren;
    logic wen;
    logic [DATA_WIDTH-1:0] wdata;
    logic [DATA_WIDTH-1:0] rdata;

    modport master (output addr, ren, wen, wdata, input rdata);
    modport slave  (input addr, ren, wen, wdata, output rdata);
endinterface
