/*
    A placeholder module to override Vivado's clock divider.
    To be used only for RTL, not synthesis and implementation.
*/
module clk_wiz_0(input clk_in1, output clk_out1);
    assign clk_out1 = clk_in1;
endmodule
