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
    localparam WIDTH = 6'd51;
    localparam HEIGHT = 6'd22;
    localparam START_POS = (X_BOUNDARY + 1) * Y_POS + X_POS;
    localparam END_POS = START_POS + 2_739;
    localparam FRAME_INTERVAL = 2'b10;

    input clk, reset, edit_mode;
    input up_ctrl, down_ctrl, left_ctrl, right_ctrl;
    input frame_end;
    output reg [13:0] start_pos, end_pos;
    output wire r, g, b;

    reg [1:0] frame_counter;
    reg [6:0] x_pos, y_pos;
    reg [6:0] x_velocity, y_velocity;
    reg [13:0] x_step, y_step;
    reg [2:0] color;
    assign r = color[0];
    assign g = color[1];
    assign b = color[2];
    
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
        end else if (frame_counter == FRAME_INTERVAL && frame_end
        && ((x_pos + x_velocity + (WIDTH - 1) - 1 == X_BOUNDARY || x_pos + x_velocity + 1 == 0) 
        || (y_pos + y_velocity + (HEIGHT - 1) - 1 == Y_BOUNDARY || y_pos + y_velocity + 1 == 0))) begin // If any collision is about to happen
            if (color == 3'b111) begin // Don't use black color
                color <= 3'b001;
            end else begin
                color <= color + 3'b1;
            end
        end
    end

    always @(posedge clk) begin
        if (reset) begin
            x_velocity <= 6'd1;
            x_step <= 6'd1;
        end else if (frame_counter == FRAME_INTERVAL && frame_end && 
        (x_pos + x_velocity + (WIDTH - 1) - 1 == X_BOUNDARY || x_pos + x_velocity + 1 == 0)) begin // Horizontal collision
            x_velocity <= -x_velocity;
            x_step <= -x_step;
        end
    end

    always @(posedge clk) begin
        if (reset) begin
            y_velocity <= 6'd1;
            y_step <= X_BOUNDARY + 1;
        end else if (frame_counter == FRAME_INTERVAL && frame_end && 
        (y_pos + y_velocity + (HEIGHT - 1) - 1 == Y_BOUNDARY || y_pos + y_velocity + 1 == 0)) begin // Vertical collision
            y_velocity <= -y_velocity;
            y_step <= -y_step;
        end
    end

    always @(posedge clk) begin
        if (reset) begin
            start_pos <= START_POS;
            end_pos <= END_POS;
            x_pos <= X_POS;
            y_pos <= Y_POS;
        end else if (frame_counter == FRAME_INTERVAL && frame_end) begin
            if (!edit_mode) begin // If not editing move automatically
                start_pos <= start_pos + x_step + y_step;
                end_pos <= end_pos + x_step + y_step;
                x_pos <= x_pos + x_velocity;
                y_pos <= y_pos + y_velocity;
            end else begin // If in edit mode control with buttons
                if (up_ctrl && y_pos > 0) begin 
                    start_pos <= start_pos - X_BOUNDARY + 1;
                    end_pos <= end_pos - X_BOUNDARY + 1;
                    y_pos <= y_pos - 6'd1;
                end else if (down_ctrl && y_pos + HEIGHT - 1 < Y_BOUNDARY) begin
                    start_pos <= start_pos + X_BOUNDARY + 1;
                    end_pos <= end_pos + X_BOUNDARY + 1;
                    y_pos <= y_pos + 6'd1;
                end else if (left_ctrl && x_pos > 0) begin
                    start_pos <= start_pos - 14'd1;
                    end_pos <= end_pos - 14'd1;
                    x_pos <= x_pos - 6'd1;
                end else if (right_ctrl && x_pos + WIDTH - 1 < X_BOUNDARY) begin
                    start_pos <= start_pos + 14'd1;
                    end_pos <= end_pos + 14'd1;
                    x_pos <= x_pos + 6'd1;
                end
            end
        end
    end
    
endmodule