package ControlPkg;

    //! CSR addresses (Basically commands to GPU)
    localparam logic [gpu_pkg::XLEN-1:0] REG_INFO = gpu_pkg::XLEN'('h0000);
    localparam logic [gpu_pkg::XLEN-1:0] REG_CONTROL = gpu_pkg::XLEN'('h0004);
    localparam logic [gpu_pkg::XLEN-1:0] REG_STATUS = gpu_pkg::XLEN'('h0008);
    localparam logic [gpu_pkg::XLEN-1:0] REG_IRQ_ENABLE = gpu_pkg::XLEN'('h000C);
    localparam logic [gpu_pkg::XLEN-1:0] REG_IRQ_STATUS = gpu_pkg::XLEN'('h0010);
    localparam logic [gpu_pkg::XLEN-1:0] IMEM_BASE = 'h2000;
    localparam logic [gpu_pkg::XLEN-1:0] DMEM_BASE = 'h4000;

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
    localparam logic [gpu_pkg::XLEN-1:0] CONTROL_START_MASK =
        gpu_pkg::XLEN'(1) << CONTROL_START_BIT;

    localparam logic [gpu_pkg::XLEN-1:0] CONTROL_STOP_MASK =
        gpu_pkg::XLEN'(1) << CONTROL_STOP_BIT;

    localparam logic [gpu_pkg::XLEN-1:0] STATUS_IDLE_MASK =
        gpu_pkg::XLEN'(1) << STATUS_IDLE_BIT;

    localparam logic [gpu_pkg::XLEN-1:0] STATUS_RUNNING_MASK =
        gpu_pkg::XLEN'(1) << STATUS_RUNNING_BIT;

    localparam logic [gpu_pkg::XLEN-1:0] STATUS_STOPPED_MASK =
        gpu_pkg::XLEN'(1) << STATUS_STOPPED_BIT;

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
