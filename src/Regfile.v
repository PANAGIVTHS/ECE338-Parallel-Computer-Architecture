module Regfile (clk, rst, addr_a, addr_b, wen, waddr, wdata, out_a, out_b);
    output [31:0] out_a, out_b;
    input clk, rst;
    input [4:0] addr_a, addr_b, waddr;
    input wen;
    input [31:0] wdata;
    reg [31:0] data [31:0];

    // Read
    always @(posedge clk or negedge rst) begin
        if (!rst) begin
            out_a <= 32'b0;
            out_b <= 32'b0;
        end else if (!wen) begin
            // Output the data when write is disabled
            out_a <= data[addr_a];
            out_b <= data[addr_b];
        end else begin
            // Read the same address you want to write, forward the data
            out_a <= (addr_a == waddr) ? wdata : data[addr_a];
            out_b <= (addr_b == waddr) ? wdata : data[addr_b];
        end
    end

    // Write
    always @(posedge clk or negedge rst) begin
        if (wen) begin
            data[waddr] <= wdata;
        end
    end

    // Reset regfile to all zeros
    always @(posedge clk or negedge rst) begin
        if (!rst) begin
            for (integer i = 0; i < 32; i = i + 1) begin
                data[i] = 32'b0;
            end
        end
    end
endmodule;
