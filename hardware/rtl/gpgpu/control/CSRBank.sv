
module CSRBank 
    import gpu_pkg::*;
    import ControlPkg::*;
#(
    parameter int unsigned SP_PER_SM = 32
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
    input logic i_complete_pulse,

    // GPU control
    output logic o_start,
    output logic o_stop,
    output logic o_clear_stopped,
    output logic o_irq
);

    localparam int unsigned XLEN = $bits(word_t);
    localparam int unsigned STRB_WIDTH = $bits(strb_t);
    localparam int unsigned BYTE_WIDTH = XLEN / STRB_WIDTH;
    localparam word_t IRQ_ALLOWED_MASK =
        word_t'(1) << IRQ_COMPLETE_BIT;

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
    // CSR: INFO (0x0000) - Read-Only Device Information
    // ========================================================================
    
    localparam int unsigned INFO_FIELD_WIDTH = XLEN / 2;

    localparam logic [INFO_FIELD_WIDTH-1:0] INTERFACE_VERSION = INFO_FIELD_WIDTH'(1);
    localparam logic [INFO_FIELD_WIDTH-1:0] SP_COUNT = INFO_FIELD_WIDTH'(SP_PER_SM);

    // ========================================================================
    // CSR: CONTROL (0x0004) - START / STOP Commands
    // ========================================================================

    logic control_write;
    assign control_write = i_write_fire && (i_addr == REG_CONTROL);
    assign o_start = control_write && (write_value == CONTROL_START_MASK);
    assign o_stop = control_write && (write_value == CONTROL_STOP_MASK);

    // ========================================================================
    // CSR: STATUS (0x0008) - Device State / STOPPED Clear
    // ========================================================================

    word_t status;
    always_comb begin
        status = '0;
        status[STATUS_IDLE_BIT] = i_idle;
        status[STATUS_RUNNING_BIT] = i_running;
        status[STATUS_STOPPED_BIT] = i_stopped && i_idle;
    end

    assign o_clear_stopped =
        i_write_fire &&
        (i_addr == REG_STATUS) &&
        (write_value & STATUS_STOPPED_MASK) != '0;

    // ========================================================================
    // CSR: IRQ_ENABLE (0x000C) - Interrupt Enable
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
    // CSR: IRQ_STATUS (0x0010) - IRQ Fired / W1C
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

            REG_INFO: begin
                if (i_write) begin
                    o_status = RSP_ACCESS_DENIED;
                end else begin
                    o_rdata = {INTERFACE_VERSION, SP_COUNT};
                end
            end

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
                    (!i_idle || i_stopped)
                ) begin
                    o_status = RSP_INVALID_STATE;
                end
            end

            REG_STATUS: begin
                if (!i_write) begin
                    o_rdata = status;
                end else if (
                    (write_value & ~STATUS_STOPPED_MASK) != '0
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

            default: begin
                o_status = RSP_INVALID_ADDRESS;
            end

        endcase
    end

endmodule
