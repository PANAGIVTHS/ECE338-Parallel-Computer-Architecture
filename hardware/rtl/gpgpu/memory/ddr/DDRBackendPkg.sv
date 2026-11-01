package DDRBackendPkg;
    
    import gpu_pkg::*;
    import AXI4FullPkg::*;
    
    localparam int unsigned XLEN = $bits(word_t);
    localparam int unsigned WINDOW_BYTES = AXI_MAX_BEATS_PER_BURST * (AXI_DATA_W / 8);
    localparam int WORD_SELECT_BIT = $clog2(XLEN / 8);

    typedef logic [max(AXI_MAX_OUTSTANDING_READS, AXI_MAX_OUTSTANDING_WRITES)-1:0] ring_index_t;
    typedef logic [AXI_DATA_W/XLEN-1:0][XLEN-1:0] beat_rdata_t;

    // Elaboration-time map checks.
    function automatic bit window_aligned(int unsigned value);
        return (value % WINDOW_BYTES) == 0;
    endfunction

    // 64-bit sums so a region ending at 2^32 cannot wrap.
    function automatic bit disjoint(int unsigned a_base, a_size, b_base, b_size);
        return (longint'(a_base) + longint'(a_size) <= longint'(b_base))
            || (longint'(b_base) + longint'(b_size) <= longint'(a_base));
    endfunction

    function automatic bit ddr_map_aligned();
        return window_aligned(FB0_BASE) && window_aligned(FB1_BASE) && window_aligned(FB_SIZE)
            && window_aligned(TEX_BASE) && window_aligned(TEX_SIZE);
    endfunction

    function automatic bit map_disjoint();
        return disjoint(DMEM_BASE, DMEM_SIZE, FB0_BASE, FB_SIZE)
            && disjoint(DMEM_BASE, DMEM_SIZE, FB1_BASE, FB_SIZE)
            && disjoint(DMEM_BASE, DMEM_SIZE, TEX_BASE, TEX_SIZE)
            && disjoint(FB0_BASE, FB_SIZE, FB1_BASE, FB_SIZE)
            && disjoint(FB0_BASE, FB_SIZE, TEX_BASE, TEX_SIZE)
            && disjoint(FB1_BASE, FB_SIZE, TEX_BASE, TEX_SIZE);
    endfunction

endpackage
