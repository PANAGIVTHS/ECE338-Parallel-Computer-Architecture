module Regfile
    import gpu_pkg::*;
#(
    parameter CORE_ID = 0
)(
    input logic clk, rst_n, i_wen,
    input word_t i_wdata,
    input reg_addr_t i_addr_a, i_addr_b, i_waddr,
    input logic i_stall,
    output word_t o_reg_a, o_reg_b
);
    //! Storage is distributed RAM (LUTRAM), which cannot be reset.
    (* ram_style = "distributed" *)
    word_t ram [REG_COUNT-1:0];
    logic [REG_COUNT-1:0] written;
    wire write_allowed = (i_waddr != '0) && (i_waddr != TXD_REGISTER);

    //! Reset values come from a per-register "written since reset" mask 
    //! instead: a register that has not been written reads as its reset value.
    function automatic word_t stored(reg_addr_t addr, logic is_written, word_t ram_value);
        return is_written ? ram_value : reg_reset_value(addr, CORE_ID);
    endfunction

    //! Read
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            o_reg_a <= '0;
            o_reg_b <= '0;
        end else if (!i_stall && !i_wen) begin
            //! Output the data when write is disabled
            o_reg_a <= stored(i_addr_a, written[i_addr_a], ram[i_addr_a]);
            o_reg_b <= stored(i_addr_b, written[i_addr_b], ram[i_addr_b]);
        end else if (!i_stall) begin
            //! Read the same address you want to write, forward the data
            o_reg_a <= (write_allowed && i_addr_a == i_waddr) ? i_wdata
                     : stored(i_addr_a, written[i_addr_a], ram[i_addr_a]);
            o_reg_b <= (write_allowed && i_addr_b == i_waddr) ? i_wdata
                     : stored(i_addr_b, written[i_addr_b], ram[i_addr_b]);
        end
    end

    //! Write (no reset: LUTRAM)
    wire write_fire = !i_stall && i_wen && write_allowed;

    always_ff @(posedge clk) begin
        if (write_fire) begin
            ram[i_waddr] <= i_wdata;
        end
    end

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            written <= '0;
        end else if (write_fire) begin
            written[i_waddr] <= 1'b1;
        end
    end
endmodule
