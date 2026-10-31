
module CSRBank 
    import gpu_pkg::*;
    import ControlPkg::*;
    import MemorySubsystemPkg::*;
#(
    parameter int unsigned SP_PER_SM = 32,
    parameter int unsigned INTERFACE_VERSION,
    parameter int unsigned CLOCK_KHZ,
    parameter int unsigned BUILD_HASH,
    parameter bit BUILD_DIRTY,
    parameter bit DDR_ENABLE
) (
    input logic clk,
    input logic rst_n,

    // CSR access
    input logic i_write,
    input word_t i_addr,
    input word_t i_wdata,
    input strb_t i_byte_en,
    input logic i_write_fire,

    output word_t o_rdata,
    output rsp_status_t o_status,

    // GPU execution state
    input logic i_idle,
    input logic i_running,
    input logic i_stopped,
    input logic i_faulted,
    input logic i_complete_pulse,

    // Fault capture (SM) and memory subsystem lock-up
    input logic i_fault,
    input logic [SP_PER_SM-1:0] i_fault_lanes,
    input mem_status_kinds_t i_fault_kinds,
    input pc_t i_fault_pc,
    input logic i_fatal,
    input mem_fatal_t i_fatal_code,

    // GPU control
    output logic o_start,
    output logic o_stop,
    output logic o_clear_stopped,
    output logic o_clear_faulted,
    output logic o_irq
);

    localparam int unsigned XLEN = $bits(word_t);
    localparam int unsigned STRB_WIDTH = $bits(strb_t);
    localparam int unsigned BYTE_WIDTH = XLEN / STRB_WIDTH;
    localparam word_t IRQ_ALLOWED_MASK = IRQ_COMPLETE_MASK;

    initial begin
        assert (STRB_WIDTH > 0)
        else $fatal(1, "STRB_WIDTH must be greater than zero");

        assert ((XLEN % STRB_WIDTH) == 0)
        else $fatal(1, "XLEN must be divisible by STRB_WIDTH");

        assert (BYTE_WIDTH == 8)
        else $fatal(1, "Each strobe must correspond to 8 bits");
    end

    // ========================================================================
    // Common CSR Access Logic
    // ========================================================================

    // Apply byte strobes to the write data.
    // i_write_fire is asserted only for an accepted, validated CSR write.

    word_t write_value;
    word_t write_mask;

    always_comb begin
        write_mask = '0;

        for (int unsigned i = 0; i < STRB_WIDTH; i++) begin
            write_mask[i*BYTE_WIDTH +: BYTE_WIDTH] = {BYTE_WIDTH{i_byte_en[i]}};
        end
    end

    assign write_value = i_wdata & write_mask;

    // ========================================================================
    // CSR: INFO - Read-Only Device Information
    // ========================================================================

    if (INTERFACE_VERSION == 0 || INTERFACE_VERSION >= (1 << INFO_FIELD_WIDTH)) begin : g_version_check
        $fatal(1, "INTERFACE_VERSION must be in 1..%0d", (1 << INFO_FIELD_WIDTH) - 1);
    end

    localparam logic [INFO_FIELD_WIDTH-1:0] VERSION_FIELD = INFO_FIELD_WIDTH'(INTERFACE_VERSION);
    localparam logic [INFO_FIELD_WIDTH-1:0] SP_COUNT = INFO_FIELD_WIDTH'(SP_PER_SM);

    // ========================================================================
    // CSR: INFO_MEM, INFO_FEATURES, INFO_CLOCK, BUILD_ID - Read-Only Identity
    // ========================================================================

    if (IMEM_ENTRIES >= (1 << INFO_FIELD_WIDTH) || DMEM_ENTRIES >= (1 << INFO_FIELD_WIDTH)) begin : g_mem_check
        $fatal(1, "IMEM_ENTRIES and DMEM_ENTRIES must fit INFO_MEM's %0d-bit fields", INFO_FIELD_WIDTH);
    end

    if (CLOCK_KHZ == 0) begin : g_clock_check
        $fatal(1, "CLOCK_KHZ must be the fabric clock in kHz, not 0");
    end

    if (BUILD_HASH >= (1 << BUILD_HASH_BITS)) begin : g_build_hash_check
        $fatal(1, "BUILD_HASH must fit BUILD_ID's %0d-bit hash field", BUILD_HASH_BITS);
    end

    localparam word_t INFO_MEM = {INFO_FIELD_WIDTH'(IMEM_ENTRIES), INFO_FIELD_WIDTH'(DMEM_ENTRIES)};
    localparam word_t INFO_FEATURES = DDR_ENABLE ? FEATURE_DDR_MASK : '0;
    localparam word_t BUILD_ID = (word_t'(BUILD_HASH) & BUILD_HASH_MASK)
                               | (BUILD_DIRTY ? BUILD_DIRTY_MASK : '0);

    // ========================================================================
    // CSR: CONTROL - START / STOP Commands
    // ========================================================================

    logic control_write;
    assign control_write = i_write_fire && (i_addr == REG_CONTROL);
    assign o_start = control_write && (write_value == CONTROL_START_MASK);
    assign o_stop = control_write && (write_value == CONTROL_STOP_MASK);

    // ========================================================================
    // CSR: STATUS - Device State / STOPPED Clear
    // ========================================================================

    word_t status;
    always_comb begin
        status = '0;
        status[STATUS_IDLE_BIT] = i_idle;
        status[STATUS_RUNNING_BIT] = i_running;
        status[STATUS_STOPPED_BIT] = i_stopped && i_idle;
        status[STATUS_FAULTED_BIT] = i_faulted;
    end

    assign o_clear_stopped =
        i_write_fire &&
        (i_addr == REG_STATUS) &&
        (write_value & STATUS_STOPPED_MASK) != '0;

    assign o_clear_faulted =
        i_write_fire &&
        (i_addr == REG_STATUS) &&
        (write_value & STATUS_FAULTED_MASK) != '0;

    // ========================================================================
    // CSR: FAULT_INFO, FAULT_LANES, FAULT_PC - Read-Only Fault Report
    // ========================================================================
    // Read straight from the SM's captures, which hold until the next START.

    if (SP_PER_SM > XLEN) begin : g_fault_lanes_check
        $fatal(1, "SP_PER_SM (%0d) must fit FAULT_LANES (%0d bits)", SP_PER_SM, XLEN);
    end

    if ($bits(fault_cause_t) > FAULT_KINDS_LSB ||
        FAULT_KINDS_LSB + MEM_STATUS_KINDS > FAULT_FATAL_LSB ||
        FAULT_FATAL_LSB + $bits(mem_fatal_t) > XLEN) begin : g_fault_info_check
        $fatal(1, "FAULT_INFO fields overlap or exceed the register");
    end

    fault_cause_t fault_cause;
    assign fault_cause = i_fatal ? FAULT_FATAL : i_fault ? FAULT_MEMORY : FAULT_NONE;

    word_t fault_info;
    assign fault_info = word_t'(fault_cause)
                      | (word_t'(i_fault_kinds) << FAULT_KINDS_LSB)
                      | (word_t'(i_fatal_code) << FAULT_FATAL_LSB);

    // ========================================================================
    // CSR: IRQ_ENABLE - Interrupt Enable
    // ========================================================================

    logic irq_enable;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            irq_enable <= '0;
        end else if (
            i_write_fire &&
            (i_addr == REG_IRQ_ENABLE) &&
            i_byte_en[IRQ_COMPLETE_BIT/BYTE_WIDTH]
        ) begin
            irq_enable <= i_wdata[IRQ_COMPLETE_BIT];
        end
    end

    // ========================================================================
    // CSR: IRQ_STATUS - IRQ Fired / W1C
    // ========================================================================

    logic irq_status;

    wire irq_status_clear =
        i_write_fire &&
        (i_addr == REG_IRQ_STATUS) &&
        write_value[IRQ_COMPLETE_BIT];

    // Priority: reset > START > completion > software W1C
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            irq_status <= '0;
        end else if (o_start) begin
            irq_status <= '0;
        end else if (i_complete_pulse) begin
            irq_status <= '1;
        end else if (irq_status_clear) begin
            irq_status <= '0;
        end
    end

    assign o_irq = rst_n && irq_enable && irq_status;

    // ========================================================================
    // CSR Read and Access Validation
    // ========================================================================

    // Combinational read data and access validation.
    // No register state is modified in this block.
    always_comb begin
        o_rdata  = '0;
        o_status = RSP_OK;
    
        case (i_addr)

            // ---------------- Identity block ----------------

            REG_INFO: begin
                if (i_write) begin
                    o_status = RSP_ACCESS_DENIED;
                end else begin
                    o_rdata = {VERSION_FIELD, SP_COUNT};
                end
            end

            REG_INFO_MEM, REG_INFO_FEATURES, REG_INFO_CLOCK, REG_BUILD_ID: begin
                if (i_write) begin
                    o_status = RSP_ACCESS_DENIED;
                end else begin
                    case (i_addr)
                        REG_INFO_MEM: o_rdata = INFO_MEM;
                        REG_INFO_FEATURES: o_rdata = INFO_FEATURES;
                        REG_INFO_CLOCK: o_rdata = word_t'(CLOCK_KHZ);
                        REG_BUILD_ID: o_rdata = BUILD_ID;
                        default: o_rdata = '0;
                    endcase
                end
            end

            // ---------------- Control block ----------------

            REG_CONTROL: begin
                if (!i_write) begin
                    o_status = RSP_ACCESS_DENIED;
                end else if (
                    (write_value &
                        ~(CONTROL_START_MASK | CONTROL_STOP_MASK)) != '0 ||
                    write_value == (CONTROL_START_MASK | CONTROL_STOP_MASK)
                ) begin
                    o_status = RSP_INVALID_REQUEST;
                end else if (
                    write_value == CONTROL_START_MASK &&
                    (!i_idle || i_stopped || i_faulted)
                ) begin
                    o_status = RSP_INVALID_STATE;
                end
            end

            REG_STATUS: begin
                if (!i_write) begin
                    o_rdata = status;
                end else if (
                    (write_value & ~(STATUS_STOPPED_MASK | STATUS_FAULTED_MASK)) != '0
                ) begin
                    o_status = RSP_ACCESS_DENIED;
                end
            end

            REG_IRQ_ENABLE: begin
                if (!i_write) begin
                    o_rdata = word_t'(irq_enable);
                end else if ((write_value & ~IRQ_ALLOWED_MASK) != '0) begin
                    o_status = RSP_INVALID_REQUEST;
                end
            end

            REG_IRQ_STATUS: begin
                if (!i_write) begin
                    o_rdata = word_t'(irq_status);
                end else if ((write_value & ~IRQ_ALLOWED_MASK) != '0) begin
                    o_status = RSP_INVALID_REQUEST;
                end
            end

            // ---------------- Fault block ----------------

            REG_FAULT_INFO, REG_FAULT_LANES, REG_FAULT_PC: begin
                if (i_write) begin
                    o_status = RSP_ACCESS_DENIED;
                end else begin
                    case (i_addr)
                        REG_FAULT_INFO: o_rdata = fault_info;
                        REG_FAULT_LANES: o_rdata = word_t'(i_fault_lanes);
                        REG_FAULT_PC: o_rdata = word_t'(i_fault_pc);
                        default: o_rdata = '0;
                    endcase
                end
            end

            default: begin
                o_status = RSP_INVALID_ADDRESS;
            end

        endcase
    end

endmodule
