module Regfile (
    input clk, rst, i_reg_wen;
    input [31:0] i_reg_wdata;
    input [4:0] i_reg_addr_a, i_reg_addr_b, i_reg_waddr;
    output [31:0] o_reg_a, o_reg_b;
);
    reg [31:0] data [31:0];

    //! Read
    always @(posedge clk or negedge rst) begin
        if (!rst) begin
            o_reg_a <= 32'b0;
            o_reg_b <= 32'b0;
        end else if (!i_reg_wen) begin
            //! Output the data when write is disabled
            o_reg_a <= data[i_reg_addr_a];
            o_reg_b <= data[i_reg_addr_b];
        end else begin
            //! Read the same address you want to write, forward the data
            o_reg_a <= (i_reg_addr_a == i_reg_waddr) ? i_reg_wdata : data[i_reg_addr_a];
            o_reg_b <= (i_reg_addr_b == i_reg_waddr) ? i_reg_wdata : data[i_reg_addr_b];
        end
    end

    //! Write
    always @(posedge clk or negedge rst) begin
        if (i_reg_wen) begin
            data[i_reg_waddr] <= i_reg_wdata;
        end
    end

    //! Reset regfile to all zeros
    always @(posedge clk or negedge rst) begin
        if (!rst) begin
            for (integer i = 0; i < 32; i = i + 1) begin
                data[i] = 32'b0;
            end
        end
    end
endmodule;
