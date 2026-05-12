module Regfile  #(
    parameter CORE_ID = 0
)(
    input clk, rst, i_wen, i_enable,
    input [31:0] i_wdata,
    input [4:0] i_addr_a, i_addr_b, i_waddr,
    output reg [31:0] o_reg_a, o_reg_b
);
    reg [31:0] data [31:0];
    integer i;

    //! Read
    always @(posedge clk) begin
        if (!rst) begin
            o_reg_a <= 32'b0;
            o_reg_b <= 32'b0;
        end else if (i_enable && !i_wen) begin
            //! Output the data when write is disabled
            o_reg_a <= (i_addr_a == 5'b0) ? 32'b0 : data[i_addr_a];
            o_reg_b <= (i_addr_b == 5'b0) ? 32'b0 : data[i_addr_b];
        end else if (i_enable) begin
            //! Read the same address you want to write, forward the data
            o_reg_a <= (i_addr_a == 5'b0) ? 32'b0 : ((i_addr_a == i_waddr) ? i_wdata : data[i_addr_a]);
            o_reg_b <= (i_addr_b == 5'b0) ? 32'b0 : ((i_addr_b == i_waddr) ? i_wdata : data[i_addr_b]);
        end
    end
    
    //! Write
    always @(posedge clk) begin
        if (!rst) begin
            for (i = 0; i < 32; i = i + 1) begin
                if (i == `TXD_REGISTER) begin
                    data[i] <= CORE_ID;
                end else begin
                    data[i] <= 32'b0;
                end
            end
        end else if (i_enable && i_wen && (i_waddr != 5'b0) && (i_waddr != `TXD_REGISTER)) begin
            data[i_waddr] <= i_wdata;
        end
    end
endmodule