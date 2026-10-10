`include "constants.svh"

module ExecutionController (
    input logic clk,
    input logic rst_n,
    input logic i_start,
    input logic i_stop,
    input logic i_clear_stopped,
    input logic i_core_complete,

    output logic [1:0] o_core_state,
    output logic o_stopped,
    output logic o_complete_pulse
);
    typedef enum logic [1:0] {
        IDLE = `CORE_IDLE,
        RESET = `CORE_RESET,
        RUNNING = `CORE_RUNNING
    } core_state_t;

    core_state_t current_state, next_state;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            current_state <= IDLE;
        end else begin
            current_state <= next_state;
        end
    end

    always_comb begin
        case (current_state)
            IDLE: begin
                if (i_start && !i_stop && !o_stopped) begin
                    next_state = RESET;
                end else begin
                    next_state = IDLE;
                end
            end
            RESET: begin
                if (i_stop) begin
                    next_state = IDLE;
                end else begin
                    next_state = RUNNING;
                end
            end
            RUNNING: begin
                if (i_stop || i_core_complete) begin
                    next_state = IDLE;
                end else begin
                    next_state = RUNNING;
                end
            end
            default: next_state = IDLE;
        endcase
    end

    always_comb begin
        case (current_state)
            IDLE: begin
                o_core_state = `CORE_IDLE;
            end
            RESET: begin
                o_core_state = `CORE_RESET;
            end
            RUNNING: begin
                o_core_state = `CORE_RUNNING;
            end
            default: begin
                o_core_state = `CORE_IDLE;
            end
        endcase
    end

    // Pre-edge normal-completion event: consumers latch it on the same edge
    // that returns RUNNING to IDLE. STOP suppresses completion, preserving abort.
    assign o_complete_pulse = (o_core_state == `CORE_RUNNING) && i_core_complete && !i_stop;

    // STOPPED inhibits START until explicitly acknowledged or externally reset.
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            o_stopped <= 1'b0;
        end else if (i_stop && current_state != IDLE) begin
            o_stopped <= 1'b1;
        end else if (i_clear_stopped) begin
            o_stopped <= 1'b0;
        end
    end

endmodule
