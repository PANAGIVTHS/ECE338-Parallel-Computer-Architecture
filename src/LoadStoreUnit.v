module LoadStoreUnit (
    input clk,
    input rst,
    input i_write_enable,
    input i_read_enable,
    input [31:0] i_addr,
    input [31:0] i_wdata,
    output [31:0] o_rdata
);

    // Create a dummy RAM and force Vivado to keep it
    (* dont_touch = "true" *) reg [31:0] data_mem [0:63];

    integer i;
    initial begin
        for (i = 0; i < 64; i = i + 1) begin
            data_mem[i] = 32'h00000000;
        end
    end

    // Synchronous Write: Write on the clock edge
    always @(posedge clk) begin
        if (i_write_enable) begin
            data_mem[i_addr[7:2]] <= i_wdata;
        end
    end

    // Combinational Read
    assign o_rdata = (i_read_enable) ? data_mem[i_addr[7:2]] : 32'h00000000;

endmodule