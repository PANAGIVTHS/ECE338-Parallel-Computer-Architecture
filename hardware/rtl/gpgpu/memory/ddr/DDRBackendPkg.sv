package DDRBackendPkg;
    
    import gpu_pkg::*;
    import AXI4FullPkg::*;
    
    localparam int unsigned WINDOW_BYTES = AXI_MAX_BEATS_PER_BURST * (AXI_DATA_W / 8);
    localparam int unsigned WORD_SELECT_BIT = $clog2(XLEN / 8);
    localparam int unsigned AXI_MAX_OUTSTANDING = max(AXI_MAX_OUTSTANDING_READS, AXI_MAX_OUTSTANDING_WRITES);
    
    typedef logic [(AXI_MAX_OUTSTANDING > 1 ? $clog2(AXI_MAX_OUTSTANDING) : 1)-1:0] ring_index_t;
    typedef logic [AXI_DATA_W/XLEN-1:0][XLEN-1:0] beat_rdata_t;

endpackage
