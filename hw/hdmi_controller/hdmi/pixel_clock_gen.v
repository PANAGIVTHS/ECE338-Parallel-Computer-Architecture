module pixel_clock_gen (
    input  wire clk,          // 50 MHz
    input  wire reset,

    output wire clk_pixel,    // ~25.1786 MHz
    output wire clk_pixel_x5, // ~125.893 MHz
    output wire locked
);

    wire clkfb;
    wire clkfb_buf;

    wire clk_pixel_raw;
    wire clk_pixel_x5_raw;

    MMCME2_BASE #(
        .BANDWIDTH("OPTIMIZED"),

        // 50 MHz input
        .CLKIN1_PERIOD(20.0),

        // VCO = 50 MHz * 17.625 = 881.25 MHz
        .DIVCLK_DIVIDE(1),
        .CLKFBOUT_MULT_F(17.625),

        // 881.25 / 7 = 125.892857 MHz
        .CLKOUT0_DIVIDE_F(7.0),

        // 881.25 / 35 = 25.178571 MHz
        .CLKOUT1_DIVIDE(35)
    )
    mmcm_inst (
        .CLKIN1(clk),

        .CLKFBIN(clkfb_buf),
        .CLKFBOUT(clkfb),

        .CLKOUT0(clk_pixel_x5_raw),
        .CLKOUT1(clk_pixel_raw),

        .LOCKED(locked),

        .PWRDWN(1'b0),
        .RST(reset),

        .CLKOUT0B(),
        .CLKOUT1B(),
        .CLKOUT2(),
        .CLKOUT2B(),
        .CLKOUT3(),
        .CLKOUT3B(),
        .CLKOUT4(),
        .CLKOUT5(),
        .CLKOUT6()
    );

    // Feedback buffer
    BUFG bufg_feedback (
        .I(clkfb),
        .O(clkfb_buf)
    );

    // Pixel clock
    BUFG bufg_pixel (
        .I(clk_pixel_raw),
        .O(clk_pixel)
    );

    // 5x TMDS serializer clock
    BUFG bufg_pixel_x5 (
        .I(clk_pixel_x5_raw),
        .O(clk_pixel_x5)
    );

endmodule