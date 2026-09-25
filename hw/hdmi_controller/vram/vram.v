module vram(
    input clk,
    input reset,
    input write_enable,
    input [13:0] write_address,
    input [13:0] read_address,
    input [2:0] write_data, 
    output wire [15:0] r,
    output wire [15:0] g,
    output wire [15:0] b
);

vram_red vram_red_inst(.clk(clk), .reset(reset), .write_enable(write_enable), .write_address(write_address), .write_data(write_data[2]), .read_address(read_address), .out(r));
vram_green vram_green_inst(.clk(clk), .reset(reset), .write_enable(write_enable), .write_address(write_address), .write_data(write_data[1]), .read_address(read_address), .out(g));
vram_blue vram_blue_inst(.clk(clk), .reset(reset), .write_enable(write_enable), .write_address(write_address), .write_data(write_data[0]), .read_address(read_address), .out(b));

endmodule