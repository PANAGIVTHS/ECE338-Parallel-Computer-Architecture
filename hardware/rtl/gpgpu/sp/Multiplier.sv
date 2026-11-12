module Multiplier
    import gpu_pkg::*;
    import pipeline_pkg::*;
    import riscv_pkg::*;
#(
    parameter int unsigned LATENCY = 3
)(
    input logic clk,
    input logic rst,
    input word_t i_operand_a,
    input word_t i_operand_b,
    input logic [2:0] i_funct3, // FUNCT3_MUL, FUNCT3_MULH, FUNCT3_MULHSU or FUNCT3_MULHU
    input logic i_global_stall,
    input mul_stage_t i_stage,
    output word_t o_result,
    output mul_stage_t o_stage,
    output mul_hazard_t o_hazards [0:LATENCY-1]
);
    typedef logic [2*$bits(word_t)-1:0] product_t;

    (* use_dsp = "yes" *) product_t mul_result [0:LATENCY-1];
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

    //? =========================
    //? PRODUCT
    //? =========================
    logic a_signed, b_signed;
    assign a_signed = (i_funct3 == FUNCT3_MULH) || (i_funct3 == FUNCT3_MULHSU);
    assign b_signed = (i_funct3 == FUNCT3_MULH);

    logic signed [$bits(word_t):0] a_ext, b_ext;
    assign a_ext = {a_signed & i_operand_a[$bits(word_t)-1], i_operand_a};
    assign b_ext = {b_signed & i_operand_b[$bits(word_t)-1], i_operand_b};

    logic signed [2*$bits(word_t)+1:0] product;
    assign product = a_ext * b_ext;

    always_ff @(posedge clk) begin
        if (!rst) begin
            for (int stage = 0; stage < LATENCY; stage++) begin
                mul_result[stage] <= '0;
            end
        end else if (!i_global_stall) begin
            mul_result[0] <= product[$bits(product_t)-1:0];
            for (int stage = 1; stage < LATENCY; stage++) begin
                mul_result[stage] <= mul_result[stage-1];
            end
        end
    end

    assign o_stage = mul_stage[LATENCY-1];
    assign o_result = o_stage.high ? mul_result[LATENCY-1][$bits(product_t)-1 -: $bits(word_t)]
                                   : mul_result[LATENCY-1][$bits(word_t)-1:0];

    for (genvar stage = 0; stage < LATENCY; stage++) begin : gen_hazards
        assign o_hazards[stage] = mul_stage[stage].hazard;
    end
endmodule
