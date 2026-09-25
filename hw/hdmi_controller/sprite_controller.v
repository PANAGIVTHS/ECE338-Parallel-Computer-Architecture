`timescale 1ns/1ps

module sprite_controller #(
    parameter X_BOUNDARY = 7'd127,
    parameter Y_BOUNDARY = 7'd95,
    parameter X_POS = 7'd0,
    parameter Y_POS = 7'd0
) (
    clk,
    reset,
    edit_mode,
    up_ctrl,
    down_ctrl,
    left_ctrl,
    right_ctrl,
    frame_end,
    start_pos,
    end_pos,
    r,
    g,
    b
);
    localparam [6:0] WIDTH = 7'd51;
    localparam [6:0] HEIGHT = 7'd23;
    localparam [6:0] MAX_X_POS = X_BOUNDARY - WIDTH + 7'd1;
    localparam [6:0] MAX_Y_POS = Y_BOUNDARY - HEIGHT + 7'd1;
    localparam [13:0] ROW_STRIDE = {7'd0, X_BOUNDARY} + 14'd1;
    localparam [13:0] START_POS = ROW_STRIDE * Y_POS + {7'd0, X_POS};
    localparam [13:0] SPRITE_SPAN = ({7'd0, HEIGHT} - 14'd1) * ROW_STRIDE
                                      + ({7'd0, WIDTH} - 14'd1);
    localparam [13:0] END_POS = START_POS + SPRITE_SPAN;
    localparam [1:0] FRAME_INTERVAL = 2'b10;

    input clk, reset, edit_mode;
    input up_ctrl, down_ctrl, left_ctrl, right_ctrl;
    input frame_end;
    output reg [13:0] start_pos, end_pos;
    output wire r, g, b;

    reg [1:0] frame_counter;
    reg [6:0] x_pos, y_pos;
    reg x_moving_right, y_moving_down;
    reg [6:0] next_x_pos, next_y_pos;
    reg next_x_moving_right, next_y_moving_down;
    reg [2:0] color;

    wire animation_tick;
    wire horizontal_collision;
    wire vertical_collision;

    assign animation_tick = frame_end && frame_counter == FRAME_INTERVAL;
    assign horizontal_collision = (x_moving_right && x_pos >= MAX_X_POS)
                                || (!x_moving_right && x_pos == 0);
    assign vertical_collision = (y_moving_down && y_pos >= MAX_Y_POS)
                              || (!y_moving_down && y_pos == 0);

    assign r = color[0];
    assign g = color[1];
    assign b = color[2];

    // Compute a reflected step.  At an edge, move back into the valid area
    // immediately instead of taking one out-of-bounds step with stale velocity.
    always @(*) begin
        next_x_pos = x_pos;
        next_y_pos = y_pos;
        next_x_moving_right = x_moving_right;
        next_y_moving_down = y_moving_down;

        if (x_moving_right) begin
            if (x_pos >= MAX_X_POS) begin
                next_x_pos = MAX_X_POS - 7'd1;
                next_x_moving_right = 1'b0;
            end else begin
                next_x_pos = x_pos + 7'd1;
            end
        end else if (x_pos == 0) begin
            next_x_pos = 7'd1;
            next_x_moving_right = 1'b1;
        end else begin
            next_x_pos = x_pos - 7'd1;
        end

        if (y_moving_down) begin
            if (y_pos >= MAX_Y_POS) begin
                next_y_pos = MAX_Y_POS - 7'd1;
                next_y_moving_down = 1'b0;
            end else begin
                next_y_pos = y_pos + 7'd1;
            end
        end else if (y_pos == 0) begin
            next_y_pos = 7'd1;
            next_y_moving_down = 1'b1;
        end else begin
            next_y_pos = y_pos - 7'd1;
        end
    end

    always @(posedge clk) begin
        if (reset) begin
            frame_counter <= 2'b0;
        end else if (frame_end) begin
            if (frame_counter == FRAME_INTERVAL) begin
                frame_counter <= 2'b0;
            end else begin
                frame_counter <= frame_counter + 2'b1;
            end
        end
    end

    always @(posedge clk) begin
        if (reset) begin
            color <= 3'b001;
        end else if (animation_tick && !edit_mode
                  && (horizontal_collision || vertical_collision)) begin
            if (color == 3'b111) begin
                color <= 3'b001;
            end else begin
                color <= color + 3'b001;
            end
        end
    end

    always @(posedge clk) begin
        if (reset) begin
            start_pos <= START_POS;
            end_pos <= END_POS;
            x_pos <= X_POS;
            y_pos <= Y_POS;
            x_moving_right <= 1'b1;
            y_moving_down <= 1'b1;
        end else if (animation_tick) begin
            if (!edit_mode) begin
                x_pos <= next_x_pos;
                y_pos <= next_y_pos;
                x_moving_right <= next_x_moving_right;
                y_moving_down <= next_y_moving_down;
                start_pos <= next_y_pos * ROW_STRIDE + {7'd0, next_x_pos};
                end_pos <= next_y_pos * ROW_STRIDE + {7'd0, next_x_pos} + SPRITE_SPAN;
            end else if (up_ctrl && y_pos > 0) begin
                start_pos <= start_pos - ROW_STRIDE;
                end_pos <= end_pos - ROW_STRIDE;
                y_pos <= y_pos - 7'd1;
            end else if (down_ctrl && y_pos < MAX_Y_POS) begin
                start_pos <= start_pos + ROW_STRIDE;
                end_pos <= end_pos + ROW_STRIDE;
                y_pos <= y_pos + 7'd1;
            end else if (left_ctrl && x_pos > 0) begin
                start_pos <= start_pos - 14'd1;
                end_pos <= end_pos - 14'd1;
                x_pos <= x_pos - 7'd1;
            end else if (right_ctrl && x_pos < MAX_X_POS) begin
                start_pos <= start_pos + 14'd1;
                end_pos <= end_pos + 14'd1;
                x_pos <= x_pos + 7'd1;
            end
        end
    end
endmodule
