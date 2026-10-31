package ControlPkg;

    //! Host register map: byte offsets inside the MMIO aperture.
    //! The host header gpgpu_platform.h is generated from these declarations.

    // Identity block (0x000-0x01C)
    localparam gpu_pkg::word_t REG_INFO = 'h0000;

    // Control block (0x020-0x03C)
    localparam gpu_pkg::word_t REG_CONTROL = 'h0020;
    localparam gpu_pkg::word_t REG_STATUS = 'h0024;
    localparam gpu_pkg::word_t REG_IRQ_ENABLE = 'h0028;
    localparam gpu_pkg::word_t REG_IRQ_STATUS = 'h002C;

    // Memory windows
    localparam gpu_pkg::word_t IMEM_BASE = 'h2000;
    localparam gpu_pkg::word_t DMEM_BASE = 'h4000;

    //! Control bits (start/stop GPU)
    localparam int unsigned CONTROL_START_BIT = 0;
    localparam int unsigned CONTROL_STOP_BIT = 1;

    //! GPU state bits
    localparam int unsigned STATUS_IDLE_BIT = 0;
    localparam int unsigned STATUS_RUNNING_BIT = 1;
    localparam int unsigned STATUS_STOPPED_BIT = 2;

    //! GPU interrupt bits
    localparam int unsigned IRQ_COMPLETE_BIT = 0;

    //! Derive masks from bit positions
    localparam gpu_pkg::word_t CONTROL_START_MASK = gpu_pkg::word_t'(1) << CONTROL_START_BIT;
    localparam gpu_pkg::word_t CONTROL_STOP_MASK = gpu_pkg::word_t'(1) << CONTROL_STOP_BIT;
    localparam gpu_pkg::word_t STATUS_IDLE_MASK = gpu_pkg::word_t'(1) << STATUS_IDLE_BIT;
    localparam gpu_pkg::word_t STATUS_RUNNING_MASK = gpu_pkg::word_t'(1) << STATUS_RUNNING_BIT;
    localparam gpu_pkg::word_t STATUS_STOPPED_MASK = gpu_pkg::word_t'(1) << STATUS_STOPPED_BIT;

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
