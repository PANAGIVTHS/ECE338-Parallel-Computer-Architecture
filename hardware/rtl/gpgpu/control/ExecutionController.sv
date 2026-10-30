module ExecutionController
    import ControlPkg::*;
(
    input logic clk,
    input logic rst_n,
    // Control from host
    input logic i_start,
    input logic i_stop,
    input logic i_clear_stopped,
    // Control from SMX
    input logic i_core_complete,
    // Memory state
    input logic i_memory_quiet,

    output core_state_t o_core_state,
    output logic o_stopped,
    output logic o_complete_pulse
);
    core_state_t current_state, next_state;
    logic stopped;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            current_state <= CORE_IDLE;
        end else begin
            current_state <= next_state;
        end
    end

    always_comb begin
        case (current_state)
            CORE_IDLE: begin
                next_state = (i_start && !i_stop && !stopped) ? CORE_RESET : CORE_IDLE;
            end
            CORE_RESET: begin
                next_state = i_stop ? CORE_IDLE : CORE_RUNNING;
            end
            CORE_RUNNING: begin
                if (i_stop || i_core_complete) begin
                    next_state = i_memory_quiet ? CORE_IDLE : CORE_DRAINING;
                end else begin
                    next_state = CORE_RUNNING;
                end
            end
            CORE_DRAINING: begin
                next_state = i_memory_quiet ? CORE_IDLE : CORE_DRAINING;
            end
            default: next_state = CORE_IDLE;
        endcase
    end

    always_comb begin
        case (current_state)
            CORE_IDLE: begin
                o_core_state = CORE_IDLE;
            end
            CORE_RESET: begin
                o_core_state = CORE_RESET;
            end
            CORE_RUNNING: begin
                o_core_state = CORE_RUNNING;
            end
            CORE_DRAINING: begin
                o_core_state = CORE_DRAINING;
            end
            default: begin
                o_core_state = CORE_IDLE;
            end
        endcase
    end

    // Completion fires only when a RUNNING/DRAINING run reaches IDLE on its own
    assign o_complete_pulse = (next_state == CORE_IDLE)
                            && (o_core_state == CORE_RUNNING || o_core_state == CORE_DRAINING);

    // STOPPED latches on a stop seen in any active state (so a stop that must
    // drain is never lost), is cleared explicitly, and is only visible on the
    // output once the FSM has actually returned to IDLE.
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            stopped <= '0;
        end else if (i_stop && o_core_state != CORE_IDLE && o_core_state != CORE_DRAINING) begin
            stopped <= '1;
        end else if (i_clear_stopped) begin
            stopped <= '0;
        end
    end

    assign o_stopped = stopped && (o_core_state == CORE_IDLE);

endmodule
