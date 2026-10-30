module MemorySinglePort #(
    parameter DEPTH = 1024,
    parameter INIT_FILE = "empty.mem"
)(
    input clk,

    MemoryInterface.slave memory
);

    (* ram_style = "block" *) 
    logic [memory.DATA_WIDTH-1:0] data [0:DEPTH-1];

    localparam int EXPECTED_ADDR_WIDTH = (DEPTH > 1) ? $clog2(DEPTH) : 1;
    initial begin
        assert (DEPTH > 0)
            else $fatal(1, "Memory DEPTH must be positive");

        assert ($bits(memory.addr) == EXPECTED_ADDR_WIDTH)
            else $fatal(1,
                "Memory address width mismatch: expected %0d, got %0d",
                EXPECTED_ADDR_WIDTH, $bits(memory.addr));
    end

    initial begin
        if (INIT_FILE != "") begin
            $readmemh(INIT_FILE, data);
        end
    end

    //! Port A
    always @(posedge clk) begin
        if (memory.ren) begin
            if (memory.wen) begin
                data[memory.addr] <= memory.wdata;
                memory.rdata <= memory.wdata;
            end else begin
                memory.rdata <= data[memory.addr];
            end
        end
    end

endmodule
