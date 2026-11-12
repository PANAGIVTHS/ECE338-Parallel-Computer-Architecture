package MemorySubsystemPkg;

    import gpu_pkg::*;
    import AXI4FullPkg::*;
    import DDRBackendPkg::*;

    (* host *) typedef enum logic [2:0] {
        ST_OK         = 3'd0,
        ST_UNMAPPED   = 3'd1, // no side effect
        ST_PERMISSION = 3'd2, // no side effect
        ST_MISALIGNED = 3'd3, // no side effect
        ST_SLVERR     = 3'd4, // AXI SLVERR; store effect undefined
        ST_DECERR     = 3'd5  // AXI DECERR; store effect undefined
    } mem_status_t;

    // Accesses the BRAM data memory issues per cycle at most: its two ports
    (* host *) localparam int unsigned BRAM_PORTS = 2;

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

    // Access size, as bits [1:0] of a RISC-V load/store funct3
    typedef enum logic [1:0] {
        MEM_SIZE_BYTE = 2'b00,
        MEM_SIZE_HALF = 2'b01,
        MEM_SIZE_WORD = 2'b10
    } mem_size_t;

    // addr is the access's byte address. wdata holds the store on its byte
    // lanes in the addressed word and wstrb selects those lanes.
    typedef struct packed {
        logic write;
        word_t addr;
        mem_size_t size;
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

    // Every access must be aligned to its own size.
    function automatic logic is_misaligned(word_t addr, mem_size_t size);
        case (size)
            MEM_SIZE_BYTE: return 1'b0;
            MEM_SIZE_HALF: return addr[0];
            default:       return addr[1:0] != 2'b00;
        endcase
    endfunction

    // ddr_enable = 0: the DDR backend is absent, so an access the map would
    // send to DDR is unmapped. Permission rules still apply first.
    function automatic decode_t decode_access(word_t addr, mem_size_t size, logic write, bit ddr_enable);
        decode_t d;
        d = '{
            target: TGT_ERR,
            status: ST_OK
        };

        if (is_misaligned(addr, size))
            d.status = ST_MISALIGNED;
        else if (in_range(addr, DMEM_BASE, DMEM_SIZE))
            d.target = TGT_BRAM;
        else if (in_range(addr, FB0_BASE, FB_SIZE) || in_range(addr, FB1_BASE, FB_SIZE)) begin
            if (write)
                d.target = TGT_DDR;
            else
                d.status = ST_PERMISSION;
        end else if (in_range(addr, GMEM_BASE, GMEM_SIZE))
            d.target = TGT_DDR;
        else
            d.status = ST_UNMAPPED;

        if (d.target == TGT_DDR && !ddr_enable) begin
            d.target = TGT_ERR;
            d.status = ST_UNMAPPED;
        end

        return d;
    endfunction

    function automatic mem_status_t axiToMemStatus(axi_resp_t axi_resp);
        mem_status_t status;

        case (axi_resp)
            AXI_RESP_EXOKAY: status = ST_OK; // AXI: EXOKAY -> ST_OK
            AXI_RESP_SLVERR: status = ST_SLVERR;
            AXI_RESP_DECERR: status = ST_DECERR;
            default: status = ST_OK;
        endcase
        
        return status;
    endfunction

    // Elaboration-time map checks.
    function automatic bit group_aligned(int unsigned value);
        return (value % GROUP_BYTES) == 0;
    endfunction

    // 64-bit sums so a region ending at 2^32 cannot wrap.
    function automatic bit disjoint(int unsigned a_base, a_size, b_base, b_size);
        return (longint'(a_base) + longint'(a_size) <= longint'(b_base))
            || (longint'(b_base) + longint'(b_size) <= longint'(a_base));
    endfunction

    function automatic bit ddr_map_aligned();
        return group_aligned(FB0_BASE) && group_aligned(FB1_BASE) && group_aligned(FB_SIZE)
            && group_aligned(GMEM_BASE) && group_aligned(GMEM_SIZE);
    endfunction

    function automatic bit map_disjoint();
        return disjoint(DMEM_BASE, DMEM_SIZE, FB0_BASE, FB_SIZE)
            && disjoint(DMEM_BASE, DMEM_SIZE, FB1_BASE, FB_SIZE)
            && disjoint(DMEM_BASE, DMEM_SIZE, GMEM_BASE, GMEM_SIZE)
            && disjoint(FB0_BASE, FB_SIZE, FB1_BASE, FB_SIZE)
            && disjoint(FB0_BASE, FB_SIZE, GMEM_BASE, GMEM_SIZE)
            && disjoint(FB1_BASE, FB_SIZE, GMEM_BASE, GMEM_SIZE);
    endfunction

endpackage
