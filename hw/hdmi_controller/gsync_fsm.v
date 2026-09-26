module gsync_fsm #(
    parameter COUNTER_WIDTH = 10,
    parameter PULSE_CYCLES = 95,
    parameter BACK_PORCH_CYCLES = 47,
    parameter DISPLAY_CYCLES = 639,
    parameter FRONT_PORCH_CYCLES = 15
) (
    clk,
    reset,
    enable,
    sync,
    rgb_enabled,
    frame_end
);
    localparam IDLE            = 4'b0;
    localparam PULSE           = 4'b1;
    localparam PULSE_END       = 4'd2;
    localparam BACK_PORCH      = 4'd3;
    localparam BACK_PORCH_END  = 4'd4;
    localparam DISPLAY         = 4'd5;
    localparam DISPLAY_END     = 4'd6;
    localparam FRONT_PORCH     = 4'd7;
    localparam FRONT_PORCH_END = 4'd8;

    input clk, reset, enable;
    output reg rgb_enabled, sync, frame_end;

    reg [3:0] current_state, next_state;
    reg [COUNTER_WIDTH-1:0] counter;
    reg state_end;

    always @(posedge clk or posedge reset) begin
        if (reset) begin
            counter <= 0;
        end else if (!enable || state_end) begin
            counter <= 0;
        end else begin
            counter <= counter + 1;
        end
    end

    always @(posedge clk or posedge reset) begin
        if (reset) begin
            current_state <= IDLE;
        end else begin
            current_state <= next_state;
        end
    end

    always @(current_state or enable or counter) begin
        case (current_state)
            IDLE: next_state = enable ? PULSE : IDLE;
            PULSE: begin
                if (!enable) next_state = IDLE;
                else if (counter == PULSE_CYCLES - 1) next_state = PULSE_END;
                else next_state = PULSE;
            end
            PULSE_END: begin
                if (!enable) next_state = IDLE;
                else if (counter == PULSE_CYCLES) next_state = BACK_PORCH;
                else next_state = PULSE;
            end
            BACK_PORCH: begin
                if (!enable) next_state = IDLE;
                else if (counter == BACK_PORCH_CYCLES - 1) next_state = BACK_PORCH_END;
                else next_state = BACK_PORCH;
            end
            BACK_PORCH_END: begin
                if (!enable) next_state = IDLE;
                else if (counter == BACK_PORCH_CYCLES) next_state = DISPLAY;
                else next_state = BACK_PORCH;
            end
            DISPLAY: begin
                if (!enable) next_state = IDLE;
                else if (counter == DISPLAY_CYCLES - 1) next_state = DISPLAY_END;
                else next_state = DISPLAY;
            end
            DISPLAY_END: begin
                if (!enable) next_state = IDLE;
                else if (counter == DISPLAY_CYCLES) next_state = FRONT_PORCH;
                else next_state = DISPLAY;
            end
            FRONT_PORCH: begin
                if (!enable) next_state = IDLE;
                else if (counter == FRONT_PORCH_CYCLES - 1) next_state = FRONT_PORCH_END;
                else next_state = FRONT_PORCH;
            end
            FRONT_PORCH_END: begin
                if (!enable) next_state = IDLE;
                else if (counter == FRONT_PORCH_CYCLES) next_state = PULSE;
                else next_state = FRONT_PORCH;
            end
            default: next_state = IDLE;
        endcase
    end

    always @(current_state or counter) begin
        case (current_state)
            IDLE: begin
                sync = 1'b1;
                rgb_enabled = 1'b0;
                state_end = 1'b1;
                frame_end = 1'b0;
            end
            PULSE: begin
                sync = 1'b0;
                rgb_enabled = 1'b0;
                state_end = 1'b0;
                frame_end = 1'b0;
            end
            PULSE_END: begin
                sync = 1'b0;
                rgb_enabled = 1'b0;
                state_end = 1'b1;
                frame_end = 1'b0;
            end
            BACK_PORCH: begin
                sync = 1'b1;
                rgb_enabled = 1'b0;
                state_end = 1'b0;
                frame_end = 1'b0;
            end
            BACK_PORCH_END: begin
                sync = 1'b1;
                rgb_enabled = 1'b0;
                state_end = 1'b1;
                frame_end = 1'b0;
            end
            DISPLAY: begin
                sync = 1'b1;
                rgb_enabled = 1'b1;
                state_end = 1'b0;
                frame_end = 1'b0;
            end
            DISPLAY_END: begin
                sync = 1'b1;
                rgb_enabled = 1'b1;
                state_end = 1'b1;
                frame_end = 1'b1;
            end
            FRONT_PORCH: begin
                sync = 1'b1;
                rgb_enabled = 1'b0;
                state_end = 1'b0;
                frame_end = 1'b0;
            end
            FRONT_PORCH_END: begin
                sync = 1'b1;
                rgb_enabled = 1'b0;
                state_end = 1'b1;
                frame_end = 1'b0;
            end
            default: begin
                sync = 1'b1;
                rgb_enabled = 1'b0;
                state_end = 1'b0;
                frame_end = 1'b0;
            end
        endcase
    end
    
endmodule