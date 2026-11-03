module Multiplier
    import gpu_pkg::*;
    import pipeline_pkg::*;
#(
    parameter int unsigned LATENCY = 3
)(
    input logic clk,
    input logic rst,
    input word_t i_operand_a,
    input word_t i_operand_b,
    input logic i_global_stall,
    input mul_stage_t i_stage,
    output word_t o_result,
    output mul_stage_t o_stage,
    output mul_hazard_t o_hazards [0:LATENCY-1]
);
    (* use_dsp = "yes" *) word_t mul_result [0:LATENCY-1];
    mul_stage_t mul_stage [0:LATENCY-1];

    initial begin
        if (LATENCY < 1) $fatal(1, "Multiplier LATENCY must be at least 1");
    end

    //? =========================
    //? MUL PIPELINE TRACKING
    //? =========================
    always_ff @(posedge clk) begin
        if (!rst) begin
            for (int stage = 0; stage < LATENCY; stage++) begin
                mul_stage[stage] <= '0;
            end
        end else if (!i_global_stall) begin
            mul_stage[0] <= i_stage;
            for (int stage = 1; stage < LATENCY; stage++) begin
                mul_stage[stage] <= mul_stage[stage-1];
            end
        end
    end


    //! The actual Multiplier, this can be replaced completely with a multiplier module
    always_ff @(posedge clk) begin
        if (!rst) begin
            for (int stage = 0; stage < LATENCY; stage++) begin
                mul_result[stage] <= '0;
            end
        end else if (!i_global_stall) begin
            mul_result[0] <= i_operand_a * i_operand_b;
            for (int stage = 1; stage < LATENCY; stage++) begin
                mul_result[stage] <= mul_result[stage-1];
            end
        end
    end

    assign o_stage = mul_stage[LATENCY-1];
    assign o_result = mul_result[LATENCY-1];

    for (genvar stage = 0; stage < LATENCY; stage++) begin : gen_hazards
        assign o_hazards[stage] = mul_stage[stage].hazard;
    end
endmodule
