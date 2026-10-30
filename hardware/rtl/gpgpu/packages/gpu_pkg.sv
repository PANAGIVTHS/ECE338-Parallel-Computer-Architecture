package gpu_pkg;

    localparam int unsigned XLEN = 32;
    localparam int unsigned BYTES_PER_WORD = XLEN / 8;
    localparam int unsigned REG_COUNT = 32;
    localparam int unsigned IMEM_ENTRIES = 2048;
    localparam int unsigned DMEM_ENTRIES = 2048;
    localparam int unsigned REG_ADDR_W = $clog2(REG_COUNT);
    localparam int unsigned IMEM_AW = $clog2(IMEM_ENTRIES);
    localparam int unsigned DMEM_AW = $clog2(DMEM_ENTRIES);
    localparam int unsigned DMEM_BASE = 'h0;
    localparam int unsigned FB0_BASE = 'h1800_0000;
    localparam int unsigned FB1_BASE = 'h1840_0000;
    localparam int unsigned TEX_BASE = 'h1880_0000;
    localparam int unsigned DMEM_SIZE = DMEM_ENTRIES * 8;
    localparam int unsigned FB_SIZE = 'h0038_4000;
    localparam int unsigned TEX_SIZE = 'h0080_0000;

    localparam logic [XLEN-1:0] INITIAL_PC = 32'h0000_0000;
    localparam logic [XLEN-1:0] NOP_INSTR = 32'h0000_0013;
    localparam logic [XLEN-1:0] STACK_P_INIT = 32'h0000_0000;
    localparam logic [REG_ADDR_W-1:0] TXD_REGISTER = 5'h1F;

    typedef logic [IMEM_AW+1:0] pc_t;
    typedef logic [REG_ADDR_W-1:0] reg_addr_t;
    typedef logic [XLEN-1:0] word_t;
    typedef logic [(XLEN/8)-1:0] strb_t;
    typedef logic [IMEM_AW-1:0] imem_idx_t;

    // Register value after reset
    function automatic word_t reg_reset_value(reg_addr_t addr, int unsigned core_id);
        if (addr == 2) return STACK_P_INIT;
        if (addr == TXD_REGISTER) return word_t'(core_id);
        return '0;
    endfunction
endpackage
