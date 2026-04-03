module Memory (
    input clk,
    input rst,
    input [9:0] i_read_addr,
    input i_read_enable,
    input [9:0] i_write_addr,
    input i_write_enable,
    input [31:0] i_write_data,
    output reg [31:0] o_out
);
    reg [31:0] data [1023:0]; //! 1024 entries of 32-bit words

    //! Read
    always @(posedge clk or negedge rst) begin
        if (!rst) begin
            o_out <= 32'b0;
        end else if (i_read_enable && !i_write_enable) begin
            o_out <= data[i_read_addr]; //! Normal read
        end else if (i_read_enable && i_write_enable) begin
            if (i_read_addr == i_write_addr) begin
                o_out <= i_write_data; //! Write on the same memory we try to read
            end
        end
    end

    //! Write
    always @(posedge clk or negedge rst) begin
        if (!rst) begin
            data[i_write_addr] <= 32'b0;
        end else if (i_write_enable) begin
            data[i_write_addr] <= i_write_data;
        end
    end
endmodule
