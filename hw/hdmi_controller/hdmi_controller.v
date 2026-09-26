module hdmi_controller (
    clk,
    rst,
    i_rgb,
    o_frame_end,
    o_hdmi_tx_p,
    o_hdmi_tx_n,
    o_hdmi_clk_p,
    o_hdmi_clk_n
);

    input reset, clk;
    input [23:0] rgb;
    wire enable = 1'b1;

    output [2:0] o_hdmi_tx_p;
    output [2:0] o_hdmi_tx_n;
    output o_hdmi_clk_p;
    output o_hdmi_clk_n;
    output o_frame_end;

    wire [6:0] hpixel, vpixel;
    wire hrgb_enabled, vrgb_enabled;
    wire hsync, vsync;
    wire active_draw = hrgb_enabled & vrgb_enabled;
    wire [23:0] rbg = {{rgb[23:16]}, {rgb[7:0]}, {rgb[15:8]}};

    // Clock generation for pixel clock
    clk_wiz_0 clk_inst(.clk_in1(clk), .clk_out1(clk_pixel), .clk_out2(clk_pixel_x5), .locked(locked));

    // TMDS encoding & serializer
    rgb2dvi_0 rgb_inst(
        .aRst_n(locked), 
        .SerialClk(clk_pixel_x5), 
        .PixelClk(clk_pixel), 
        .vid_pHSync(hsync), 
        .vid_pVSync(vsync), 
        .vid_pData(rbg), 
        .vid_pVDE(active_draw), 
        .TMDS_Clk_p(hdmi_clk_p), 
        .TMDS_Clk_n(hdmi_clk_n), 
        .TMDS_Data_p(hdmi_tx_p), 
        .TMDS_Data_n(hdmi_tx_n)
    );

    // Horizontal sync controller
    gsync_controller #(
        .COUNTER_WIDTH(10),
        .PULSE_CYCLES(95),
        .BACK_PORCH_CYCLES(47),
        .DISPLAY_CYCLES(639),
        .FRONT_PORCH_CYCLES(15),
        .UPSCALE_WIDTH(0),
        .UPSCALE_CYCLES(0),
        .RESET_PIXEL(128)
    )
    hsync_controller_inst(
        .clk(clk_pixel), 
        .reset(rst), 
        .enable(enable), 
        .sync(hsync), 
        .rgb_enabled(hrgb_enabled), 
        .pixel(hpixel)
    );

    // Vertical sync controller
    gsync_controller #(
        .COUNTER_WIDTH(19),
        .PULSE_CYCLES(1599),
        .BACK_PORCH_CYCLES(26399),
        .DISPLAY_CYCLES(383999),
        .FRONT_PORCH_CYCLES(7999),
        .UPSCALE_WIDTH(0),
        .UPSCALE_CYCLES(0),
        .RESET_PIXEL(96)
    )
    vsync_controller_inst(
        .clk(clk_pixel), 
        .reset(rst), 
        .enable(enable), 
        .sync(vsync), 
        .rgb_enabled(vrgb_enabled), 
        .pixel(vpixel),
        .frame_end(o_frame_end)
    );

endmodule