package MemorySubsystemPkg;

    import gpu_pkg::*;

    typedef enum logic [2:0] {
        MEM_OK         = 3'd0,
        MEM_OUT_BOUNDS = 3'd1,
        MEM_AXI_ERROR  = 3'd2,
        MEM_PERMISSION = 3'd3,
        MEM_MISALIGNED = 3'd4,
        MEM_ABORTED    = 3'd5
    } mem_fault_t;

    typedef enum logic [1:0] { 
        TGT_ERR = 2'd0,
        TGT_BRAM = 2'd1,
        TGT_DDR = 2'd2
    } mem_target_e;

    typedef struct packed {
        logic write;
        word_t addr;
        word_t wdata;
        strb_t wstrb; // for future use
    } mem_req_t;

    typedef struct packed {
        word_t rdata;
        mem_fault_t fault;
    } mem_rsp_t;

    typedef struct packed {
        mem_target_e target;
        mem_fault_t fault;
    } decode_t;

    function automatic logic in_range(word_t a, base, size);
        return (a >= base) && (a - base < size);
    endfunction

    function automatic decode_t decode(word_t addr, logic write);
        decode_t d;
        d = '{
            target: TGT_ERR,
            fault: MEM_OK
        };

        if (addr[1:0] != 2'b00) 
            d.fault = MEM_MISALIGNED;
        else if (in_range(addr, DMEM_BASE, DMEM_SIZE)) 
            d.target = TGT_BRAM;
        else if (in_range(addr, FB0_BASE, FB_SIZE) || in_range(addr, FB1_BASE, FB_SIZE)) begin
            if (write)
                d.target = TGT_DDR;
            else
                d.fault = MEM_PERMISSION;
        end else if (in_range(addr, TEX_BASE, TEX_SIZE)) begin
            if (~write)
                d.target = TGT_DDR;
            else
                d.fault = MEM_PERMISSION;
        end else
            d.fault = MEM_OUT_BOUNDS;

        return d;
    endfunction

endpackage
