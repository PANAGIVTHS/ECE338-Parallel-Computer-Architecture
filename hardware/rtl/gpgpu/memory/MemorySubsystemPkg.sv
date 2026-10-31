package MemorySubsystemPkg;

    import gpu_pkg::*;

    // AXI burst geometry: a window is the longest HP burst, so a burst never
    // crosses a window and every DDR region must be window-aligned.
    localparam int unsigned AXI_DATA_W = 64;
    localparam int unsigned MAX_BEATS = 16;
    localparam int unsigned WINDOW_BYTES = MAX_BEATS * (AXI_DATA_W / 8);

    (* host *) typedef enum logic [2:0] {
        ST_OK         = 3'd0,
        ST_UNMAPPED   = 3'd1, // no side effect
        ST_PERMISSION = 3'd2, // no side effect
        ST_MISALIGNED = 3'd3, // no side effect
        ST_SLVERR     = 3'd4, // AXI SLVERR; store effect undefined
        ST_DECERR     = 3'd5  // AXI DECERR; store effect undefined
    } mem_status_t;

    // One bit per non-OK status code: bit k-1 is ST code k (fault reporting).
    localparam int unsigned MEM_STATUS_KINDS = (1 << $bits(mem_status_t)) - 1;
    typedef logic [MEM_STATUS_KINDS-1:0] mem_status_kinds_t;

    // Why the subsystem locked up (o_fatal_code); sticky until rst_n.
    (* host *) typedef enum logic [2:0] {
        FATAL_NONE       = 3'd0,
        FATAL_RLAST      = 3'd1, // RLAST early or missing
        FATAL_UNEXPECTED = 3'd2, // B/R with nothing outstanding, or wrong ID
        FATAL_TIMEOUT    = 3'd3, // no AXI progress for AXI_TIMEOUT cycles
        FATAL_INTERNAL   = 3'd4  // invariant violation
    } mem_fatal_t;

    typedef enum logic [1:0] {
        TGT_ERR = 2'd0,
        TGT_BRAM = 2'd1,
        TGT_DDR = 2'd2
    } mem_target_e;

    typedef struct packed {
        logic write;
        word_t addr;
        word_t wdata;
        strb_t wstrb;
    } mem_req_t;

    typedef struct packed {
        word_t rdata;
        mem_status_t status;
    } mem_rsp_t;

    typedef struct packed {
        mem_target_e target;
        mem_status_t status;
    } decode_t;

    function automatic logic in_range(word_t a, base, size);
        return (a >= base) && (a - base < size);
    endfunction

    // ddr_enable = 0: the DDR backend is absent, so an access the map would
    // send to DDR is unmapped. Permission rules still apply first.
    function automatic decode_t decode_access(word_t addr, logic write, bit ddr_enable);
        decode_t d;
        d = '{
            target: TGT_ERR,
            status: ST_OK
        };

        if (addr[1:0] != 2'b00)
            d.status = ST_MISALIGNED;
        else if (in_range(addr, DMEM_BASE, DMEM_SIZE))
            d.target = TGT_BRAM;
        else if (in_range(addr, FB0_BASE, FB_SIZE) || in_range(addr, FB1_BASE, FB_SIZE)) begin
            if (write)
                d.target = TGT_DDR;
            else
                d.status = ST_PERMISSION;
        end else if (in_range(addr, TEX_BASE, TEX_SIZE)) begin
            if (~write)
                d.target = TGT_DDR;
            else
                d.status = ST_PERMISSION;
        end else
            d.status = ST_UNMAPPED;

        if (d.target == TGT_DDR && !ddr_enable) begin
            d.target = TGT_ERR;
            d.status = ST_UNMAPPED;
        end

        return d;
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
