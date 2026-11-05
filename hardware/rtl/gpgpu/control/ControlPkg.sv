package ControlPkg;

    //! Host register map: byte offsets inside the MMIO aperture.

    // Identity block (0x000-0x01C)
    (* host *) localparam gpu_pkg::word_t REG_INFO = 'h0000;
    (* host *) localparam gpu_pkg::word_t REG_INFO_MEM = 'h0004;
    (* host *) localparam gpu_pkg::word_t REG_INFO_FEATURES = 'h0008;
    (* host *) localparam gpu_pkg::word_t REG_INFO_CLOCK = 'h000C;
    (* host *) localparam gpu_pkg::word_t REG_BUILD_ID = 'h0010;

    // Control block (0x020-0x03C)
    (* host *) localparam gpu_pkg::word_t REG_CONTROL = 'h0020;
    (* host *) localparam gpu_pkg::word_t REG_STATUS = 'h0024;
    (* host *) localparam gpu_pkg::word_t REG_IRQ_ENABLE = 'h0028;
    (* host *) localparam gpu_pkg::word_t REG_IRQ_STATUS = 'h002C;

    // Fault block (0x040-0x05C)
    (* host *) localparam gpu_pkg::word_t REG_FAULT_INFO = 'h0040;
    (* host *) localparam gpu_pkg::word_t REG_FAULT_LANES = 'h0044;
    (* host *) localparam gpu_pkg::word_t REG_FAULT_PC = 'h0048;

    // Memory windows
    (* host *) localparam gpu_pkg::word_t IMEM_BASE = 'h2000;
    (* host *) localparam gpu_pkg::word_t DMEM_BASE = 'h4000;

    //! Control bits (start/stop GPU)
    localparam int unsigned CONTROL_START_BIT = 0;
    localparam int unsigned CONTROL_STOP_BIT = 1;

    //! GPU state bits
    localparam int unsigned STATUS_IDLE_BIT = 0;
    localparam int unsigned STATUS_RUNNING_BIT = 1;
    localparam int unsigned STATUS_STOPPED_BIT = 2;
    localparam int unsigned STATUS_FAULTED_BIT = 3;

    //! GPU interrupt bits
    localparam int unsigned IRQ_COMPLETE_BIT = 0;

    //! INFO_FEATURES bits
    localparam int unsigned FEATURE_DDR_BIT = 0;

    //! BUILD_ID fields: [BUILD_HASH_BITS-1:0] short hash of the last RTL commit,
    //! then the dirty bit (uncommitted RTL changes)
    localparam int unsigned BUILD_HASH_BITS = 28;
    localparam int unsigned BUILD_DIRTY_BIT = BUILD_HASH_BITS;

    //! INFO = {interface version, SPs per SM} and INFO_MEM = {IMEM words,
    //! DMEM words}: two half-word fields each
    localparam int unsigned INFO_FIELD_WIDTH = gpu_pkg::XLEN / 2;
    localparam gpu_pkg::word_t INFO_FIELD_MASK = (gpu_pkg::word_t'(1) << INFO_FIELD_WIDTH) - 1;

    //! Derive masks from bit positions
    (* host *) localparam gpu_pkg::word_t CONTROL_START_MASK = gpu_pkg::word_t'(1) << CONTROL_START_BIT;
    (* host *) localparam gpu_pkg::word_t CONTROL_STOP_MASK = gpu_pkg::word_t'(1) << CONTROL_STOP_BIT;
    (* host *) localparam gpu_pkg::word_t STATUS_IDLE_MASK = gpu_pkg::word_t'(1) << STATUS_IDLE_BIT;
    (* host *) localparam gpu_pkg::word_t STATUS_RUNNING_MASK = gpu_pkg::word_t'(1) << STATUS_RUNNING_BIT;
    (* host *) localparam gpu_pkg::word_t STATUS_STOPPED_MASK = gpu_pkg::word_t'(1) << STATUS_STOPPED_BIT;
    (* host *) localparam gpu_pkg::word_t STATUS_FAULTED_MASK = gpu_pkg::word_t'(1) << STATUS_FAULTED_BIT;
    (* host *) localparam gpu_pkg::word_t FEATURE_DDR_MASK = gpu_pkg::word_t'(1) << FEATURE_DDR_BIT;
    (* host *) localparam gpu_pkg::word_t BUILD_HASH_MASK = (gpu_pkg::word_t'(1) << BUILD_HASH_BITS) - 1;
    (* host *) localparam gpu_pkg::word_t BUILD_DIRTY_MASK = gpu_pkg::word_t'(1) << BUILD_DIRTY_BIT;
    (* host *) localparam gpu_pkg::word_t IRQ_COMPLETE_MASK = gpu_pkg::word_t'(1) << IRQ_COMPLETE_BIT;
    (* host *) localparam int unsigned INFO_VERSION_LSB = INFO_FIELD_WIDTH;
    (* host *) localparam gpu_pkg::word_t INFO_VERSION_MASK = INFO_FIELD_MASK << INFO_VERSION_LSB;
    (* host *) localparam gpu_pkg::word_t INFO_SP_COUNT_MASK = INFO_FIELD_MASK;
    (* host *) localparam int unsigned INFO_MEM_IMEM_LSB = INFO_FIELD_WIDTH;
    (* host *) localparam gpu_pkg::word_t INFO_MEM_IMEM_MASK = INFO_FIELD_MASK << INFO_MEM_IMEM_LSB;
    (* host *) localparam gpu_pkg::word_t INFO_MEM_DMEM_MASK = INFO_FIELD_MASK;

    //! FAULT_INFO: [cause], [kinds] (bit k-1 = some lane got ST code k) and
    //! [fatal] (the subsystem's mem_fatal_t)
    (* host *) typedef enum logic [3:0] {
        FAULT_NONE         = 4'd0,
        FAULT_MEMORY       = 4'd1, // a kernel access failed: see kinds and FAULT_LANES
        FAULT_POSTED_WRITE = 4'd2, // reserved: posted DDR write error (lane unknown)
        FAULT_FATAL        = 4'd3  // the memory subsystem locked up: see fatal; needs a reset
    } fault_cause_t;
    (* host *) localparam int unsigned FAULT_KINDS_LSB = 4;
    (* host *) localparam int unsigned FAULT_FATAL_LSB = 16;
    (* host *) localparam gpu_pkg::word_t FAULT_CAUSE_MASK =
        (gpu_pkg::word_t'(1) << $bits(fault_cause_t)) - 1;
    (* host *) localparam gpu_pkg::word_t FAULT_KINDS_MASK =
        ((gpu_pkg::word_t'(1) << MemorySubsystemPkg::MEM_STATUS_KINDS) - 1) << FAULT_KINDS_LSB;
    (* host *) localparam gpu_pkg::word_t FAULT_FATAL_MASK =
        ((gpu_pkg::word_t'(1) << $bits(MemorySubsystemPkg::mem_fatal_t)) - 1) << FAULT_FATAL_LSB;

    typedef enum logic [1:0] {
        CORE_IDLE = 2'b00,
        CORE_RESET = 2'b01,
        CORE_RUNNING = 2'b10,
        CORE_DRAINING = 2'b11
    } core_state_t;

    //! Response type
    typedef enum logic [2:0] {
        RSP_OK = 3'b000,
        RSP_INVALID_ADDRESS = 3'b001,
        RSP_ACCESS_DENIED = 3'b010,
        RSP_INVALID_STATE = 3'b011,
        RSP_INVALID_REQUEST = 3'b100
    } rsp_status_t;

endpackage
