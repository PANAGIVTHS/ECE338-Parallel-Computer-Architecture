module hdmi_controller (
    clk,
    reset,
    edit_mode, 
    up_ctrl,
    down_ctrl,
    left_ctrl,
    right_ctrl,
    hdmi_tx_p,
    hdmi_tx_n,
    hdmi_clk_p,
    hdmi_clk_n
);

    input reset, clk, edit_mode;
    input up_ctrl, down_ctrl, left_ctrl, right_ctrl;

    wire enable = 1'b1;
    output [2:0] hdmi_tx_p;
    output [2:0] hdmi_tx_n;
    output hdmi_clk_p;
    output hdmi_clk_n;

    wire [2:0] rgb;
    wire [6:0] hpixel, vpixel;
    wire [2:0] hpixel_upscale_counter;
    wire hrgb_enabled, vrgb_enabled;
    wire active_draw = hrgb_enabled & vrgb_enabled;
    wire [23:0] rbg24 = {
        {8{rgb[2]}}, 
        {8{rgb[0]}},
        {8{rgb[1]}}
   };

    wire [13:0] write_address;
    wire [2:0] write_data;

    // Clock generation for pixel clock
    clk_wiz_0 clk_inst(.clk_in1(clk), .clk_out1(clk_pixel), .clk_out2(clk_pixel_x5));
    ResetDebouncer reset_debouncer_inst(.clk(clk_pixel), .input_bounce(reset), .debounced(debounced_reset), .debounced_off(), .debounced_on());
    InputDebouncer enable_debouncer_inst(.clk(clk_pixel), .reset(debounced_reset), .input_bounce(enable), .debounced(debounced_enable), .posedge_pulse());
    InputDebouncer edit_debouncer_inst(.clk(clk_pixel), .reset(debounced_reset), .input_bounce(edit_mode), .debounced(debounced_edit), .posedge_pulse());
    InputDebouncer up_debouncer_inst(.clk(clk_pixel), .reset(debounced_reset), .input_bounce(up_ctrl), .debounced(up_debounced), .posedge_pulse());
    InputDebouncer down_debouncer_inst(.clk(clk_pixel), .reset(debounced_reset), .input_bounce(down_ctrl), .debounced(down_debounced), .posedge_pulse());
    InputDebouncer left_debouncer_inst(.clk(clk_pixel), .reset(debounced_reset), .input_bounce(left_ctrl), .debounced(left_debounced), .posedge_pulse());
    InputDebouncer right_debouncer_inst(.clk(clk_pixel), .reset(debounced_reset), .input_bounce(right_ctrl), .debounced(right_debounced), .posedge_pulse());

    // TMDS encoding & serializer
    rgb2dvi_0 rgb_inst(.aRst_n(1'b1), .SerialClk(clk_pixel_x5), .PixelClk(clk_pixel), .vid_pHSync(hsync), .vid_pVSync(vsync), .vid_pData(rbg24), .vid_pVDE(active_draw), 
    .TMDS_Clk_p(hdmi_clk_p), .TMDS_Clk_n(hdmi_clk_n), .TMDS_Data_p(hdmi_tx_p), .TMDS_Data_n(hdmi_tx_n));
    
    renderer renderer_inst(.clk(clk_pixel), .reset(debounced_reset), .edit_mode(debounced_edit),  .up_ctrl(up_debounced), .down_ctrl(down_debounced), 
    .left_ctrl(left_debounced), .right_ctrl(right_debounced), .frame_end(frame_end), .write_enable(write_enable), .write_address(write_address), 
    .write_data(write_data));

    pixel_controller #(
        .UPSCALE_WIDTH(3),
        .UPSCALE_CYCLES(4)
    )
    pixel_controller_inst(.clk(clk_pixel), .reset(debounced_reset), .write_enable(write_enable), .write_address(write_address), .write_data(write_data), .hrgb_enabled(hrgb_enabled), .vrgb_enabled(vrgb_enabled), 
    .hpixel(hpixel), .hpixel_upscale_counter(hpixel_upscale_counter), .vpixel(vpixel), .rgb(rgb));

    // Horizontal sync controller
    gsync_controller #(
        .COUNTER_WIDTH(10),
        .PULSE_CYCLES(95),
        .BACK_PORCH_CYCLES(47),
        .DISPLAY_CYCLES(639),
        .FRONT_PORCH_CYCLES(15),
        .UPSCALE_WIDTH(3),
        .UPSCALE_CYCLES(4),
        .RESET_PIXEL(128)
    )
    hsync_controller_inst(.clk(clk_pixel), .reset(debounced_reset), .enable(debounced_enable), .sync(hsync), .rgb_enabled(hrgb_enabled), .pixel(hpixel), .upscale_counter(hpixel_upscale_counter), .frame_end());

    // Vertical sync controller
    gsync_controller #(
        .COUNTER_WIDTH(19),
        .PULSE_CYCLES(1599),
        .BACK_PORCH_CYCLES(26399),
        .DISPLAY_CYCLES(383999),
        .FRONT_PORCH_CYCLES(7999),
        .UPSCALE_WIDTH(12),
        .UPSCALE_CYCLES(3999),
        .RESET_PIXEL(96)
    )
    vsync_controller_inst(.clk(clk_pixel), .reset(debounced_reset), .enable(debounced_enable), .sync(vsync), .rgb_enabled(vrgb_enabled), .pixel(vpixel), .upscale_counter(), .frame_end(frame_end));

endmodule