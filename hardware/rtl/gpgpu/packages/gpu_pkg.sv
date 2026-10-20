package gpu_pkg;

    localparam int unsigned XLEN = 32;
    localparam int unsigned REG_COUNT = 32;
    localparam int unsigned IMEM_ENTRIES = 2048;
    localparam int unsigned DMEM_ENTRIES = 2048;
    localparam int unsigned REG_ADDR_W = $clog2(REG_COUNT);
    localparam int unsigned IMEM_AW = $clog2(IMEM_ENTRIES);
    localparam int unsigned DMEM_AW = $clog2(DMEM_ENTRIES);

    localparam logic [31:0] INITIAL_PC = 32'h0000_0000;
    localparam logic [31:0] NOP_INSTR = 32'h0000_0013;
    localparam logic [31:0] STACK_P_INIT = 32'h0000_0000;
    localparam logic [4:0] TXD_REGISTER = 5'h1F;

    typedef logic [IMEM_AW+1:0] pc_t;
    typedef logic [REG_ADDR_W-1:0] reg_addr_t;
    typedef logic [XLEN-1:0] word_t;
    typedef logic [IMEM_AW-1:0] imem_idx_t;
endpackage
