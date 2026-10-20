module Regfile
    import gpu_pkg::*;
#(
    parameter CORE_ID = 0
)(
    input logic clk, rst, i_wen,
    input word_t i_wdata,
    input reg_addr_t i_addr_a, i_addr_b, i_waddr,
    input logic i_global_stall,
    output word_t o_reg_a, o_reg_b
);
    word_t data [REG_COUNT-1:0];
    wire write_allowed = (i_waddr != '0) && (i_waddr != TXD_REGISTER);

    //! Read
    always_ff @(posedge clk) begin
        if (!rst) begin
            o_reg_a <= '0;
            o_reg_b <= '0;
        end else if (!i_global_stall && !i_wen) begin
            //! Output the data when write is disabled
            o_reg_a <= (i_addr_a == '0) ? '0 : data[i_addr_a];
            o_reg_b <= (i_addr_b == '0) ? '0 : data[i_addr_b];
        end else if (!i_global_stall) begin
            //! Read the same address you want to write, forward the data
            o_reg_a <= (i_addr_a == '0) ? '0 :
                       (write_allowed && i_addr_a == i_waddr) ? i_wdata : data[i_addr_a];
            o_reg_b <= (i_addr_b == '0) ? '0 :
                       (write_allowed && i_addr_b == i_waddr) ? i_wdata : data[i_addr_b];
        end
    end

    //! Write
    always_ff @(posedge clk) begin
        if (!rst) begin
            for (int i = 0; i < REG_COUNT; i++) begin
                if (i == 2) begin
                    data[i] <= STACK_P_INIT;
                end else if (i == TXD_REGISTER) begin
                    data[i] <= CORE_ID;
                end else begin
                    data[i] <= '0;
                end
            end
        end else if (!i_global_stall && i_wen && write_allowed) begin
            data[i_waddr] <= i_wdata;
        end
    end
endmodule