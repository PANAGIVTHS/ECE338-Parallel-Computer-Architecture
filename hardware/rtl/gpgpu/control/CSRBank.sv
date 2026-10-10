
`include "constants.svh"

module CSRBank #(
    parameter int unsigned SP_PER_SM = 32
) (
    input  logic        clk,
    input  logic        rst_n,

    // CSR access
    input  logic        i_write,
    input  logic [31:0] i_addr,
    input  logic [31:0] i_wdata,
    input  logic [3:0]  i_byte_en,
    input  logic        i_write_fire,

    output logic [31:0] o_rdata,
    output logic [2:0]  o_status,

    // GPU execution state
    input  logic        i_idle,
    input  logic        i_running,
    input  logic        i_stopped,
    input  logic        i_complete_pulse,

    // GPU control
    output logic        o_start,
    output logic        o_stop,
    output logic        o_clear_stopped,
    output logic        o_irq
);

    // ========================================================================
    // Common CSR Access Logic
    // ========================================================================

    // Apply byte strobes to the write data.
    // i_write_fire is asserted only for an accepted, validated CSR write.
    wire [31:0] write_value = i_wdata & {
        {8{i_byte_en[3]}},
        {8{i_byte_en[2]}},
        {8{i_byte_en[1]}},
        {8{i_byte_en[0]}}
    };

    // ========================================================================
    // CSR: INFO (0x0000) - Read-Only Device Information
    // ========================================================================

    localparam logic [15:0] INTERFACE_VERSION = 16'd1;
    localparam logic [15:0] SP_COUNT = 16'(SP_PER_SM);

    // ========================================================================
    // CSR: CONTROL (0x0004) - START / STOP Commands
    // ========================================================================

    wire control_write = i_write_fire && (i_addr == `REG_CONTROL);
    assign o_start = control_write && (write_value == `CONTROL_START);
    assign o_stop = control_write && (write_value == `CONTROL_STOP);

    // ========================================================================
    // CSR: STATUS (0x0008) - Device State / STOPPED Clear
    // ========================================================================

    wire [31:0] status = {
        29'b0,
        i_stopped && i_idle,
        i_running,
        i_idle
    };

    assign o_clear_stopped =
        i_write_fire &&
        (i_addr == `REG_STATUS) &&
        (write_value & `STATUS_STOPPED) != 32'b0;

    // ========================================================================
    // CSR: IRQ_ENABLE (0x000C) - Interrupt Enable
    // ========================================================================

    logic irq_enable;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            irq_enable <= 1'b0;
        end else if (
            i_write_fire &&
            (i_addr == `REG_IRQ_ENABLE) &&
            i_byte_en[0]
        ) begin
            irq_enable <= i_wdata[0];
        end
    end

    // ========================================================================
    // CSR: IRQ_STATUS (0x0010) - IRQ Fired / W1C
    // ========================================================================

    logic irq_status;

    wire irq_status_clear =
        i_write_fire &&
        (i_addr == `REG_IRQ_STATUS) &&
        write_value[0];

    // Priority: reset > START > completion > software W1C
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            irq_status <= 1'b0;
        end else if (o_start) begin
            irq_status <= 1'b0;
        end else if (i_complete_pulse) begin
            irq_status <= 1'b1;
        end else if (irq_status_clear) begin
            irq_status <= 1'b0;
        end
    end

    assign o_irq = rst_n && irq_enable && irq_status;

    // ========================================================================
    // CSR Read and Access Validation
    // ========================================================================

    // Combinational read data and access validation.
    // No register state is modified in this block.
    always_comb begin
        o_rdata  = 32'b0;
        o_status = `RSP_OK;
    
        case (i_addr)

            `REG_INFO: begin
                if (i_write) begin
                    o_status = `RSP_ACCESS_DENIED;
                end else begin
                    o_rdata = {INTERFACE_VERSION, SP_COUNT};
                end
            end

            `REG_CONTROL: begin
                if (!i_write) begin
                    o_status = `RSP_ACCESS_DENIED;
                end else if (
                    (write_value &
                        ~(`CONTROL_START | `CONTROL_STOP)) != 32'b0 ||
                    write_value == (`CONTROL_START | `CONTROL_STOP)
                ) begin
                    o_status = `RSP_INVALID_REQUEST;
                end else if (
                    write_value == `CONTROL_START &&
                    (!i_idle || i_stopped)
                ) begin
                    o_status = `RSP_INVALID_STATE;
                end
            end

            `REG_STATUS: begin
                if (!i_write) begin
                    o_rdata = status;
                end else if (
                    (write_value & ~`STATUS_STOPPED) != 32'b0
                ) begin
                    o_status = `RSP_ACCESS_DENIED;
                end
            end

            `REG_IRQ_ENABLE: begin
                if (!i_write) begin
                    o_rdata = {31'b0, irq_enable};
                end else if (write_value[31:1] != 31'b0) begin
                    o_status = `RSP_INVALID_REQUEST;
                end
            end

            `REG_IRQ_STATUS: begin
                if (!i_write) begin
                    o_rdata = {31'b0, irq_status};
                end else if (write_value[31:1] != 31'b0) begin
                    o_status = `RSP_INVALID_REQUEST;
                end
            end

            default: begin
                o_status = `RSP_INVALID_ADDRESS;
            end

        endcase
    end

endmodule
