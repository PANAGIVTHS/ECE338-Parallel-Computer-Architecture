module tmds_top (
    input clk_pixel,
    input clk_pixel_x5,
    input rst,
    input active_draw,
    input hsync,
    input vsync,
    input [2:0] rgb,
    output wire [2:0] hdmi_tx_p,
    output wire [2:0] hdmi_tx_n,
    output wire hdmi_clk_p,
    output wire hdmi_clk_n
);
    wire [2:0] tmds_signal;
    wire [9:0] tmds_10b [2:0];

    tmds_encoder tmds_red (
        .clk(clk_pixel), // your pixel clock
        .rst(rst),
        .data_in({8{rgb[2]}}),
        // 8-bit value
        .control_in(2'b0),
        .ve_in(active_draw),
        .tmds_out(tmds_10b[2])
    );

    tmds_encoder tmds_green(
        .clk(clk_pixel), // your pixel clock
        .rst(rst),
        // system reset
        .data_in({8{rgb[1]}}),
        // 8-bit value
        .control_in(2'b0),
        .ve_in(active_draw),
        .tmds_out(tmds_10b[1])
    );

    tmds_encoder tmds_blue(
        .clk(clk_pixel), // your pixel clock
        .rst(rst),
        // system reset
        .data_in({8{rgb[0]}}),
        // 8-bit value
        .control_in({vsync, hsync}),
        .ve_in(active_draw),
        .tmds_out(tmds_10b[0])
    );

    tmds_serializer red_ser(
        .clk_pixel_in(clk_pixel), // your pixel clock
        .clk_5x_in(clk_pixel_x5),
        // your x5 clock
        .rst_in(rst),
        // system reset
        .tmds_in(tmds_10b[2]),
        .tmds_out(tmds_signal[2])
    );

    tmds_serializer green_ser(
        .clk_pixel_in(clk_pixel), // your pixel clock
        .clk_5x_in(clk_pixel_x5),
        // your x5 clock
        .rst_in(rst),
        // system reset
        .tmds_in(tmds_10b[1]),
        .tmds_out(tmds_signal[1])
    );

    tmds_serializer blue_ser(
        .clk_pixel_in(clk_pixel), // your pixel clock
        .clk_5x_in(clk_pixel_x5),
        // your x5 clock
        .rst_in(rst),
        // system reset
        .tmds_in(tmds_10b[0]),
        .tmds_out(tmds_signal[0])
    );

OBUFDS OBUFDS_blue (.I(tmds_signal[0]), .O(hdmi_tx_p[0]), .OB(hdmi_tx_n[0]));
OBUFDS OBUFDS_green(.I(tmds_signal[1]), .O(hdmi_tx_p[1]), .OB(hdmi_tx_n[1]));
OBUFDS OBUFDS_red (.I(tmds_signal[2]), .O(hdmi_tx_p[2]), .OB(hdmi_tx_n[2]));
OBUFDS OBUFDS_clock(.I(clk_pixel), .O(hdmi_clk_p), .OB(hdmi_clk_n));

endmodule