//! The performance counter bank (docs/perf-counters-spec.md): the counters
//! of PerfPkg, cleared at the start of every run and read by the host
//! through the CSR read path while the GPU is idle.
//!
//! Every event is registered once before it is counted, together with the
//! run state that decides the window, so the counters add no paths into the
//! logic they observe and the partitions stay exact.
module PerfCounters
    import gpu_pkg::*;
    import ControlPkg::*;
    import PerfPkg::*;
#(
    parameter int unsigned NUM_WARPS,
    parameter int unsigned SP_PER_SM,
    parameter int unsigned WR_SLOTS,   // DDR write ring slots
    parameter int unsigned RD_SLOTS,   // DDR read ring slots
    parameter int unsigned BRAM_PORTS  // BRAM accesses issued per cycle at most
) (
    input logic clk,
    input logic rst_n,

    // Run window: START to IDLE
    input core_state_t i_core_state,

    // Each warp's leaf this cycle (counted in RUNNING only)
    input perf_warp_leaf_t i_warp_leaf [NUM_WARPS],

    // DDR write channels
    input logic i_aw_valid,
    input logic i_aw_ready,
    input logic i_w_valid,
    input logic i_w_ready,
    input logic i_w_pending, // a slot's beats wait for W

    // DDR write ring
    input logic [$clog2(WR_SLOTS+1)-1:0] i_wr_inflight, // occupied slots
    input logic [$clog2(WR_SLOTS+1)-1:0] i_wr_owed,     // bursts sent, B not arrived
    input logic i_wr_ring_full,
    input logic [$clog2(SP_PER_SM+1)-1:0] i_wr_lane_stores, // lanes admitted this cycle

    // DDR read channels
    input logic i_ar_valid,
    input logic i_ar_ready,
    input logic i_r_valid,
    input logic i_r_ready,

    // DDR read ring
    input logic [$clog2(RD_SLOTS+1)-1:0] i_rd_owed, // bursts whose AR is accepted, RLAST not arrived
    input logic [$clog2(SP_PER_SM+1)-1:0] i_rd_lane_loads, // lanes admitted this cycle

    // BRAM data memory
    input logic [$clog2(BRAM_PORTS+1)-1:0] i_bram_accesses, // accesses issued
    input logic [$clog2(BRAM_PORTS+1)-1:0] i_bram_deferred, // picks deferred

    // Read port (combinational, like CSRBank): o_hit when i_addr is the low
    // or high word of a defined counter
    input word_t i_addr,
    output logic o_hit,
    output word_t o_rdata
);

    if (NUM_WARPS < 1 || NUM_WARPS > PERF_MAX_WARPS) begin : g_warps_check
        $fatal(1, "NUM_WARPS (%0d) must be 1 to PERF_MAX_WARPS (%0d)", NUM_WARPS, PERF_MAX_WARPS);
    end

    if (PERF_BASE + PERF_SIZE > IMEM_BASE) begin : g_region_check
        $fatal(1, "The perf block (0x%0h + 0x%0h) overlaps IMEM_BASE (0x%0h)", PERF_BASE, PERF_SIZE, IMEM_BASE);
    end

    // Widest per-cycle increment of any counter
    function automatic int unsigned max2(int unsigned x, int unsigned y);
        return (x > y) ? x : y;
    endfunction
    localparam int unsigned INC_W = max2(max2($bits(i_wr_inflight), $bits(i_rd_owed)),
                                        max2($bits(i_wr_lane_stores), $bits(i_bram_accesses)));
    typedef logic [INC_W-1:0] inc_t;

    //& =============================================
    //& Registered events and run state
    //& =============================================
    core_state_t state_q;
    perf_warp_leaf_t warp_leaf_q [NUM_WARPS];
    logic aw_valid_q, aw_ready_q, w_valid_q, w_ready_q, w_pending_q, wr_ring_full_q;
    logic [$bits(i_wr_inflight)-1:0] wr_inflight_q, wr_owed_q;
    logic [$bits(i_wr_lane_stores)-1:0] wr_lane_stores_q, rd_lane_loads_q;
    logic ar_valid_q, ar_ready_q, r_valid_q, r_ready_q;
    logic [$bits(i_rd_owed)-1:0] rd_owed_q;
    logic [$bits(i_bram_accesses)-1:0] bram_accesses_q, bram_deferred_q;
    logic in_run_prev;

    // The run's cycles, in the registered domain; its first cycle clears
    logic in_run, run_first, running;
    assign in_run = state_q != CORE_IDLE;
    assign run_first = in_run & ~in_run_prev;
    assign running = state_q == CORE_RUNNING;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            state_q <= CORE_IDLE;
            in_run_prev <= 1'b0;
        end else begin
            state_q <= i_core_state;
            in_run_prev <= in_run;
        end
    end

    always_ff @(posedge clk) begin
        warp_leaf_q <= i_warp_leaf;
        aw_valid_q <= i_aw_valid;
        aw_ready_q <= i_aw_ready;
        w_valid_q <= i_w_valid;
        w_ready_q <= i_w_ready;
        w_pending_q <= i_w_pending;
        wr_inflight_q <= i_wr_inflight;
        wr_owed_q <= i_wr_owed;
        wr_ring_full_q <= i_wr_ring_full;
        wr_lane_stores_q <= i_wr_lane_stores;
        ar_valid_q <= i_ar_valid;
        ar_ready_q <= i_ar_ready;
        r_valid_q <= i_r_valid;
        r_ready_q <= i_r_ready;
        rd_owed_q <= i_rd_owed;
        rd_lane_loads_q <= i_rd_lane_loads;
        bram_accesses_q <= i_bram_accesses;
        bram_deferred_q <= i_bram_deferred;
    end

    //& =============================================
    //& What each counter adds this cycle
    //& =============================================
    // A global counter's increment, from the registered events
    function automatic inc_t global_inc_of(perf_global_t id);
        case (id)
            PERF_KERNEL_CYCLES:   return inc_t'(1'b1);
            PERF_RUN_RESET:       return inc_t'(state_q == CORE_RESET);
            PERF_RUN_DRAIN:       return inc_t'(state_q == CORE_DRAINING);

            PERF_AW_TRANSFER:     return inc_t'(aw_valid_q && aw_ready_q);
            PERF_AW_BLOCKED:      return inc_t'(aw_valid_q && !aw_ready_q);
            PERF_AW_IDLE:         return inc_t'(!aw_valid_q);

            PERF_W_TRANSFER:      return inc_t'(w_valid_q && w_ready_q);
            PERF_W_BLOCKED:       return inc_t'(w_valid_q && !w_ready_q);
            PERF_W_WAIT_AW:       return inc_t'(!w_valid_q && w_pending_q);
            PERF_W_IDLE:          return inc_t'(!w_valid_q && !w_pending_q);

            PERF_WR_INFLIGHT_SUM: return inc_t'(wr_inflight_q);
            PERF_WR_OWED_SUM:     return inc_t'(wr_owed_q);
            PERF_WR_RING_FULL:    return inc_t'(wr_ring_full_q);

            PERF_AR_TRANSFER:     return inc_t'(ar_valid_q && ar_ready_q);
            PERF_AR_BLOCKED:      return inc_t'(ar_valid_q && !ar_ready_q);
            PERF_AR_IDLE:         return inc_t'(!ar_valid_q);

            PERF_R_TRANSFER:      return inc_t'(r_valid_q && r_ready_q);
            PERF_R_BLOCKED:       return inc_t'(r_valid_q && !r_ready_q);
            PERF_R_WAIT:          return inc_t'(!r_valid_q && rd_owed_q != '0);
            PERF_R_IDLE:          return inc_t'(!r_valid_q && rd_owed_q == '0);

            PERF_RD_OWED_SUM:     return inc_t'(rd_owed_q);

            PERF_WR_LANE_STORES:  return inc_t'(wr_lane_stores_q);
            PERF_RD_LANE_LOADS:   return inc_t'(rd_lane_loads_q);

            PERF_BRAM_ACCESSES:   return inc_t'(bram_accesses_q);
            PERF_BRAM_BUSY:       return inc_t'(bram_accesses_q != '0);
            PERF_BRAM_DEFERRED:   return inc_t'(bram_deferred_q);

            default:              return '0;
        endcase
    endfunction

    inc_t global_inc [PERF_GLOBAL_COUNT];
    inc_t warp_inc [NUM_WARPS][PERF_WARP_LEAF_COUNT];

    always_comb begin
        for (int unsigned c = 0; c < PERF_GLOBAL_COUNT; c++) begin
            global_inc[c] = global_inc_of(perf_global_t'(c));
        end
        for (int unsigned w = 0; w < NUM_WARPS; w++) begin
            for (int unsigned l = 0; l < PERF_WARP_LEAF_COUNT; l++) begin
                warp_inc[w][l] = inc_t'(running && warp_leaf_q[w] == perf_warp_leaf_t'(l));
            end
        end
    end

    //& =============================================
    //& Counters
    //& =============================================
    perf_count_t global_count [PERF_GLOBAL_COUNT];
    perf_count_t warp_count [NUM_WARPS][PERF_WARP_LEAF_COUNT];

    function automatic perf_count_t next_count(perf_count_t count, inc_t inc, logic first, logic counting);
        if (first) return perf_count_t'(inc);
        if (counting) return count + perf_count_t'(inc);
        return count;
    endfunction

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            for (int unsigned c = 0; c < PERF_GLOBAL_COUNT; c++) begin
                global_count[c] <= '0;
            end
            for (int unsigned w = 0; w < NUM_WARPS; w++) begin
                for (int unsigned l = 0; l < PERF_WARP_LEAF_COUNT; l++) begin
                    warp_count[w][l] <= '0;
                end
            end
        end else begin
            for (int unsigned c = 0; c < PERF_GLOBAL_COUNT; c++) begin
                global_count[c] <= next_count(global_count[c], global_inc[c], run_first, in_run);
            end
            for (int unsigned w = 0; w < NUM_WARPS; w++) begin
                for (int unsigned l = 0; l < PERF_WARP_LEAF_COUNT; l++) begin
                    warp_count[w][l] <= next_count(warp_count[w][l], warp_inc[w][l], run_first, in_run);
                end
            end
        end
    end

    //& =============================================
    //& Read port
    //& =============================================
    localparam int unsigned SLOT_LSB = $clog2(PERF_COUNTER_BYTES);
    localparam int unsigned WARP_LSB = $clog2(PERF_WARP_STRIDE);

    if ((1 << SLOT_LSB) != PERF_COUNTER_BYTES || (1 << WARP_LSB) != PERF_WARP_STRIDE) begin : g_pow2_check
        $fatal(1, "PERF_COUNTER_BYTES and PERF_WARP_STRIDE must be powers of two");
    end

    word_t global_offset, warp_offset;
    int unsigned global_slot, warp_bank, warp_slot;
    logic word_aligned, hi_word;
    perf_count_t selected;

    assign global_offset = i_addr - PERF_GLOBAL_BASE;
    assign warp_offset = i_addr - PERF_WARP_BASE;
    assign global_slot = int'(global_offset >> SLOT_LSB);
    assign warp_bank = int'(warp_offset >> WARP_LSB);
    assign warp_slot = int'((warp_offset & (PERF_WARP_STRIDE - 1)) >> SLOT_LSB);
    assign word_aligned = i_addr[$clog2(BYTES_PER_WORD)-1:0] == '0;
    assign hi_word = i_addr[SLOT_LSB-1:0] == PERF_HI_OFFSET[SLOT_LSB-1:0];

    always_comb begin
        o_hit = 1'b0;
        selected = '0;
        if (word_aligned && i_addr >= PERF_GLOBAL_BASE && i_addr < PERF_WARP_BASE) begin
            if (global_slot < PERF_GLOBAL_COUNT) begin
                o_hit = 1'b1;
                selected = global_count[global_slot];
            end
        end else if (word_aligned && i_addr >= PERF_WARP_BASE && i_addr < PERF_BASE + PERF_SIZE) begin
            if (warp_bank < NUM_WARPS && warp_slot < PERF_WARP_LEAF_COUNT) begin
                o_hit = 1'b1;
                selected = warp_count[warp_bank][warp_slot];
            end
        end
    end

    assign o_rdata = hi_word ? selected[PERF_COUNTER_W-1 -: $bits(word_t)] : selected[$bits(word_t)-1:0];

endmodule
