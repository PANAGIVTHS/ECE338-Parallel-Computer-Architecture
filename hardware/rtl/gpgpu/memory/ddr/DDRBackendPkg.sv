package DDRBackendPkg;
    
    import gpu_pkg::*;
    import AXI4FullPkg::*;
    
    localparam int unsigned GROUP_BYTES = AXI_MAX_BEATS_PER_BURST * (AXI_DATA_W / 8);
    localparam int unsigned GROUP_LSB = $clog2(GROUP_BYTES);
    localparam int unsigned BEAT_LSB = $clog2(AXI_DATA_W / 8);
    localparam int unsigned WORD_SELECT_BIT = $clog2(XLEN / 8);

    localparam int unsigned AXI_MAX_OUTSTANDING = max(AXI_MAX_OUTSTANDING_READS, AXI_MAX_OUTSTANDING_WRITES);
    // Cycles the slave may owe progress before FATAL_TIMEOUT; 0 disables it.
    localparam int unsigned AXI_TIMEOUT = 1 << 20;
    localparam int unsigned RING_INDEX_W = AXI_MAX_OUTSTANDING > 1 ? $clog2(AXI_MAX_OUTSTANDING) : 1;

    typedef logic [RING_INDEX_W-1:0] ring_index_t;
    typedef logic [AXI_DATA_W/XLEN-1:0][XLEN-1:0] beat_rdata_t;
    typedef logic [XLEN-GROUP_LSB-1:0] ring_group_t;
    typedef logic [GROUP_LSB-BEAT_LSB-1:0] beat_t;
    typedef logic [AXI_MAX_BEATS_PER_BURST-1:0] beat_mask_t;
    typedef logic [$clog2(AXI_DATA_W/XLEN)-1:0] word_sel_t;

    function automatic ring_group_t group_of(input word_t addr);
        return ring_group_t'(addr[XLEN-1:GROUP_LSB]);
    endfunction

    // Every DDR region lies in one aligned window of 2^DDR_WINDOW_BITS bytes:
    // the address bits above it are the same for every DDR access, so two
    // groups of DDR accesses differ in the group bits inside the window.
    localparam int unsigned DDR_LOW = (FB0_BASE < FB1_BASE ? (FB0_BASE < TEX_BASE ? FB0_BASE : TEX_BASE)
                                                           : (FB1_BASE < TEX_BASE ? FB1_BASE : TEX_BASE));
    localparam int unsigned DDR_HIGH_END = max(max(FB0_BASE + FB_SIZE, FB1_BASE + FB_SIZE), TEX_BASE + TEX_SIZE);
    localparam int unsigned DDR_WINDOW_BITS = $clog2((DDR_LOW ^ (DDR_HIGH_END - 1)) + 1);
    localparam int unsigned GROUP_KEY_W = DDR_WINDOW_BITS > GROUP_LSB ? DDR_WINDOW_BITS - GROUP_LSB : 1;
    typedef logic [GROUP_KEY_W-1:0] group_key_t;

    function automatic group_key_t group_key(input ring_group_t group);
        return group_key_t'(group);
    endfunction

    function automatic beat_t beat_of(input word_t addr);
        return beat_t'(addr[GROUP_LSB-1:BEAT_LSB]);
    endfunction

    function automatic word_t word_of(input ring_group_t group, input beat_t beat);
        return {group, beat, BEAT_LSB'(0)};
    endfunction

    function automatic word_sel_t word_sel_of(input word_t addr);
        return addr[WORD_SELECT_BIT +: $bits(word_sel_t)];
    endfunction

endpackage
