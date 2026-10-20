package control_pkg;

    //! CSR addresses (Basically commands to GPU)
    localparam logic [31:0] REG_INFO = 32'h0000;
    localparam logic [31:0] REG_CONTROL = 32'h0004;
    localparam logic [31:0] REG_STATUS = 32'h0008;
    localparam logic [31:0] REG_IRQ_ENABLE = 32'h000C;
    localparam logic [31:0] REG_IRQ_STATUS = 32'h0010;
    localparam logic [31:0] IMEM_BASE = 32'h2000;
    localparam logic [31:0] DMEM_BASE = 32'h4000;

    //! CSR addresses (start/stop to GPU)
    localparam logic [31:0] CONTROL_START_MASK = 32'h00000001;
    localparam logic [31:0] CONTROL_STOP_MASK = 32'h00000002;

    //! GPU state
    localparam logic [31:0] STATUS_IDLE_MASK = 32'h00000001;
    localparam logic [31:0] STATUS_RUNNING_MASK = 32'h00000002;
    localparam logic [31:0] STATUS_STOPPED_MASK = 32'h00000004;

    typedef enum logic [1:0] {
        CORE_IDLE = 2'b00,
        CORE_RESET = 2'b01,
        CORE_RUNNING = 2'b10
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
