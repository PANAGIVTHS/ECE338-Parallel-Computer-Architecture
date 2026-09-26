module gsync_controller #(
    parameter COUNTER_WIDTH = 10,
    parameter PULSE_CYCLES = 95,
    parameter BACK_PORCH_CYCLES = 47,
    parameter DISPLAY_CYCLES = 639,
    parameter FRONT_PORCH_CYCLES = 15,
    parameter UPSCALE_WIDTH = 3,
    parameter UPSCALE_CYCLES = 4,
    parameter RESET_PIXEL = 128
) (
    clk,
    reset,
    enable,
    sync,
    rgb_enabled,
    pixel,
    upscale_counter,
    frame_end
);
    input clk, reset, enable;
    output wire rgb_enabled, sync;
    output reg [6:0] pixel;
    output reg [UPSCALE_WIDTH-1:0] upscale_counter;
    output wire frame_end;
    
    gsync_fsm #(
        .COUNTER_WIDTH(COUNTER_WIDTH),
        .PULSE_CYCLES(PULSE_CYCLES),
        .BACK_PORCH_CYCLES(BACK_PORCH_CYCLES),
        .DISPLAY_CYCLES(DISPLAY_CYCLES),
        .FRONT_PORCH_CYCLES(FRONT_PORCH_CYCLES)
    ) 
    gsync_fsm_inst(.clk(clk), .reset(reset), .enable(enable), .sync(sync), .rgb_enabled(rgb_enabled), .frame_end(frame_end));

    always @(posedge clk) begin
        if (reset) begin
            upscale_counter <= 0;
        end else if (!enable || !rgb_enabled || upscale_counter == UPSCALE_CYCLES) begin
            upscale_counter <= 0;
        end else begin
            upscale_counter <= upscale_counter + 1;
        end
    end

    always @(posedge clk) begin
        if (reset) begin
            pixel <= 7'b0;
        end else if (!enable || pixel == RESET_PIXEL) begin
            pixel <= 7'b0;
        end else if (rgb_enabled && upscale_counter == UPSCALE_CYCLES) begin
            pixel <= pixel + 7'b1;
        end
    end
    
endmodule