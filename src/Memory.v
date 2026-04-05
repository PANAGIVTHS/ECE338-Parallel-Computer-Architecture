module Memory #(
    parameter DEPTH = 1024,
    parameter INIT_FILE = "program.mem"
) (
    input clk,
    input rst,
    input [9:0] i_read_addr,
    input i_read_enable,
    input [9:0] i_write_addr,
    input i_write_enable,
    input [31:0] i_write_data,
    output reg [31:0] o_out
);
    (* ram_style = "block" *) reg [31:0] data [0:DEPTH-1];

    // initial begin
    //     $readmemh(INIT_FILE, data);
    // end

    // Write
    always @(posedge clk) begin
        if (i_write_enable) begin
            data[i_write_addr] <= i_write_data;
        end
    end

    // Read
    always @(posedge clk) begin
        if (i_read_enable) begin
            o_out <= data[i_read_addr]; 
        end
    end

endmodule
