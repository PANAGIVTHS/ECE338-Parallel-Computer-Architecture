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
    localparam int unsigned XW = $bits(word_t) + 1;   // operand with its sign bit
    localparam int unsigned LO_W = 17;                // unsigned low half: 18-bit DSP port
    localparam int unsigned HI_W = XW - LO_W;
    // Register stages inside the DSPs, from the output side: PREG, MREG, AREG/BREG.
    // LATENCY 3 fills all of them; stages beyond 3 go after the adder.
    localparam int unsigned IN_REGS = (LATENCY >= 3) ? 1 : 0;
    localparam int unsigned M_REGS = (LATENCY >= 2) ? 1 : 0;
    localparam int unsigned OUT_REGS = (LATENCY > 3) ? LATENCY - 3 : 0;

    typedef logic [2*$bits(word_t)-1:0] product_t;

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

    //! Four independent DSPs, one per partial product. A registered cascade
    //! (PCOUT -> PCIN) would need one more stage per hop to keep every PREG,
    //! so the partial products are summed in fabric instead.
    logic signed [LO_W:0] a_lo, b_lo; // zero-extended
    logic signed [HI_W-1:0] a_hi, b_hi;
    assign a_lo = {1'b0, a_ext[LO_W-1:0]};
    assign b_lo = {1'b0, b_ext[LO_W-1:0]};
    assign a_hi = a_ext[XW-1:LO_W];
    assign b_hi = b_ext[XW-1:LO_W];

    logic signed [LO_W:0] a_lo_q, b_lo_q;
    logic signed [HI_W-1:0] a_hi_q, b_hi_q;
    (* use_dsp = "yes" *) logic signed [2*LO_W+1:0] pp_ll, pp_ll_m, pp_ll_p;
    (* use_dsp = "yes" *) logic signed [LO_W+HI_W:0] pp_hl, pp_hl_m, pp_hl_p;
    (* use_dsp = "yes" *) logic signed [LO_W+HI_W:0] pp_lh, pp_lh_m, pp_lh_p;
    (* use_dsp = "yes" *) logic signed [2*HI_W-1:0] pp_hh, pp_hh_m, pp_hh_p;

    if (IN_REGS == 1) begin : gen_in_regs
        always_ff @(posedge clk) begin
            if (!rst) begin
                a_lo_q <= '0; b_lo_q <= '0; a_hi_q <= '0; b_hi_q <= '0;
            end else if (!i_global_stall) begin
                a_lo_q <= a_lo; b_lo_q <= b_lo; a_hi_q <= a_hi; b_hi_q <= b_hi;
            end
        end
    end else begin : gen_no_in_regs
        assign a_lo_q = a_lo;
        assign b_lo_q = b_lo;
        assign a_hi_q = a_hi;
        assign b_hi_q = b_hi;
    end

    assign pp_ll = a_lo_q * b_lo_q;
    assign pp_hl = a_hi_q * b_lo_q;
    assign pp_lh = a_lo_q * b_hi_q;
    assign pp_hh = a_hi_q * b_hi_q;

    if (M_REGS == 1) begin : gen_m_regs
        always_ff @(posedge clk) begin
            if (!rst) begin
                pp_ll_m <= '0; pp_hl_m <= '0; pp_lh_m <= '0; pp_hh_m <= '0;
            end else if (!i_global_stall) begin
                pp_ll_m <= pp_ll; pp_hl_m <= pp_hl; pp_lh_m <= pp_lh; pp_hh_m <= pp_hh;
            end
        end
    end else begin : gen_no_m_regs
        assign pp_ll_m = pp_ll;
        assign pp_hl_m = pp_hl;
        assign pp_lh_m = pp_lh;
        assign pp_hh_m = pp_hh;
    end

    always_ff @(posedge clk) begin
        if (!rst) begin
            pp_ll_p <= '0; pp_hl_p <= '0; pp_lh_p <= '0; pp_hh_p <= '0;
        end else if (!i_global_stall) begin
            pp_ll_p <= pp_ll_m; pp_hl_p <= pp_hl_m; pp_lh_p <= pp_lh_m; pp_hh_p <= pp_hh_m;
        end
    end

    localparam int unsigned UP_W = $bits(product_t) - LO_W;
    (* use_dsp = "no" *) logic signed [UP_W-1:0] sum_hi;
    product_t product, result;
    // Everything above bit LO_W: pp_ll's upper half, pp_hh at bit 2*LO_W, and the
    // two middle products, which start at bit LO_W.
    assign sum_hi = {pp_hh_p[UP_W-LO_W-1:0], pp_ll_p[2*LO_W-1:LO_W]}
                  + UP_W'(pp_hl_p) + UP_W'(pp_lh_p);
    assign product = {sum_hi, pp_ll_p[LO_W-1:0]};

    if (OUT_REGS == 0) begin : gen_no_out_regs
        assign result = product;
    end else begin : gen_out_regs
        product_t out_q [0:OUT_REGS-1];
        always_ff @(posedge clk) begin
            if (!rst) begin
                for (int s = 0; s < OUT_REGS; s++) out_q[s] <= '0;
            end else if (!i_global_stall) begin
                out_q[0] <= product;
                for (int s = 1; s < OUT_REGS; s++) out_q[s] <= out_q[s-1];
            end
        end
        assign result = out_q[OUT_REGS-1];
    end

    assign o_stage = mul_stage[LATENCY-1];
    assign o_result = o_stage.high ? result[$bits(product_t)-1 -: $bits(word_t)]
                                   : result[$bits(word_t)-1:0];

    for (genvar stage = 0; stage < LATENCY; stage++) begin : gen_hazards
        assign o_hazards[stage] = mul_stage[stage].hazard;
    end
endmodule
