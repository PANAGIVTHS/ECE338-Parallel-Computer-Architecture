package DDRBackendPkg;

    import gpu_pkg::*;
    import MemorySubsystemPkg::*;

    // AXI burst geometry: a window is the longest HP burst, so a burst never
    // crosses a window and every DDR region must be window-aligned.
    localparam int unsigned AXI_DATA_W = 64;
    localparam int unsigned MAX_BEATS = 16;
    localparam int unsigned WINDOW_BYTES = MAX_BEATS * (AXI_DATA_W / 8);
    localparam int unsigned XLEN = $bits(word_t);
    localparam int WORD_SELECT_BIT = $clog2(BYTES_PER_WORD);
    
    typedef logic [$clog2(MAX_BEATS)-1:0] ring_index_t;
    typedef logic [AXI_DATA_W/XLEN-1:0][XLEN-1:0] beat_rdata_t;
    typedef logic [1:0] ddr_resp_t;

    function automatic mem_status_t ddrToMemStatus(logic [1:0] rd_resp);
        mem_status_t status;

        case (rd_resp)
            2'b01: status = ST_OK; // AXI: EXOKAY -> ST_OK
            2'b10: status = ST_SLVERR;
            2'b11: status = ST_DECERR;
            default: status = ST_OK;
        endcase
        
        return status;
    endfunction

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
