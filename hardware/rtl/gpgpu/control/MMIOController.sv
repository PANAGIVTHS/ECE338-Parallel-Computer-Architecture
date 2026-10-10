`include "constants.svh"

module MMIOController (
    input  logic        clk,
    input  logic        rst_n,

    // Host request
    input  logic        i_req_valid,
    output logic        o_req_ready,
    input  logic        i_req_write,
    input  logic [31:0] i_req_addr,
    input  logic [31:0] i_req_wdata,
    input  logic [3:0]  i_req_wstrb,

    // Host response
    output logic        o_rsp_valid,
    input  logic        i_rsp_ready,
    output logic [31:0] o_rsp_rdata,
    output logic [2:0]  o_rsp_status,

    // GPU state and local memories
    input  logic        i_idle,
    MemoryInterface.master imem,
    MemoryInterface.master dmem,

    // CSR bank
    output logic        o_csr_write_fire,
    input  logic [31:0] i_csr_rdata,
    input  logic [2:0]  i_csr_status
);

    // ========================================================================
    // Transaction State Machine
    // ========================================================================

    typedef enum logic [1:0] {
        ACCESS_IDLE,
        ACCESS_MEMORY,
        ACCESS_CAPTURE,
        ACCESS_RESPONSE
    } access_state_t;

    access_state_t current_state, next_state;

    wire request_accepted = i_req_valid && o_req_ready;

    assign o_req_ready = current_state == ACCESS_IDLE;
    assign o_rsp_valid = current_state == ACCESS_RESPONSE;

    always_ff @(posedge clk) begin
        if (!rst_n)
            current_state <= ACCESS_IDLE;
        else
            current_state <= next_state;
    end

    always_comb begin
        next_state = current_state;

        case (current_state)
            ACCESS_IDLE: begin
                if (request_accepted)
                    next_state = decoded_memory
                        ? ACCESS_MEMORY
                        : ACCESS_RESPONSE;
            end

            ACCESS_MEMORY: begin
                next_state = memory_write
                    ? ACCESS_RESPONSE
                    : ACCESS_CAPTURE;
            end

            ACCESS_CAPTURE: begin
                next_state = ACCESS_RESPONSE;
            end

            ACCESS_RESPONSE: begin
                if (i_rsp_ready)
                    next_state = ACCESS_IDLE;
            end

            default: next_state = ACCESS_IDLE;
        endcase
    end


    // ========================================================================
    // Address Decoding and Access Validation
    // ========================================================================

    wire csr_selected = i_req_addr < `IMEM_BASE;

    wire imem_selected =
        i_req_addr >= `IMEM_BASE &&
        i_req_addr < (`IMEM_BASE + 32'd4 * `IMEM_ENTRIES);

    wire dmem_selected =
        i_req_addr >= `DMEM_BASE &&
        i_req_addr < (`DMEM_BASE + 32'd4 * `DMEM_ENTRIES);

    logic [31:0] decoded_rdata;
    logic [2:0]  decoded_status;
    logic        decoded_memory;

    always_comb begin
        decoded_rdata  = 32'b0;
        decoded_status = `RSP_OK;
        decoded_memory = 1'b0;

        if (i_req_addr[1:0] != 2'b00) begin
            decoded_status = `RSP_INVALID_ADDRESS;

        end else if (imem_selected || dmem_selected) begin
            if (!i_idle) begin
                decoded_status = `RSP_INVALID_STATE;

            end else if (
                i_req_write &&
                i_req_wstrb != 4'b1111 &&
                i_req_wstrb != 4'b0000
            ) begin
                decoded_status = `RSP_INVALID_REQUEST;

            end else begin
                // A zero-strobe memory write is an acknowledged no-op.
                decoded_memory =
                    !i_req_write || (i_req_wstrb != 4'b0000);
            end

        end else if (csr_selected) begin
            decoded_rdata  = i_csr_rdata;
            decoded_status = i_csr_status;

        end else begin
            decoded_status = `RSP_INVALID_ADDRESS;
        end
    end


    // ========================================================================
    // CSR Access
    // ========================================================================

    // Only accepted and validated CSR writes produce side effects.
    assign o_csr_write_fire =
        request_accepted &&
        csr_selected &&
        i_req_write &&
        decoded_status == `RSP_OK;


    // ========================================================================
    // Local Memory Access
    // ========================================================================

    localparam int unsigned HOST_ADDR_WIDTH =
        (`IMEM_AW > `DMEM_AW) ? `IMEM_AW : `DMEM_AW;

    // Retain the request payload while the BRAM operation completes.
    logic memory_imem;
    logic memory_write;
    logic [HOST_ADDR_WIDTH-1:0] memory_address;
    logic [31:0] memory_wdata;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            memory_imem    <= 1'b0;
            memory_write   <= 1'b0;
            memory_address <= '0;
            memory_wdata   <= 32'b0;

        end else if (request_accepted && decoded_memory) begin
            memory_imem  <= imem_selected;
            memory_write <= i_req_write;
            memory_wdata <= i_req_wdata;

            memory_address <= HOST_ADDR_WIDTH'(
                (i_req_addr -
                    (imem_selected ? `IMEM_BASE : `DMEM_BASE)) >> 2
            );
        end
    end

    // Drive the selected synchronous BRAM port.
    wire memory_access =
        current_state == ACCESS_MEMORY && i_idle;

    assign imem.addr  = memory_address[`IMEM_AW-1:0];
    assign imem.wdata = memory_wdata;
    assign imem.ren   = memory_access && memory_imem;
    assign imem.wen   = imem.ren && memory_write;

    assign dmem.addr  = memory_address[`DMEM_AW-1:0];
    assign dmem.wdata = memory_wdata;
    assign dmem.ren   = memory_access && !memory_imem;
    assign dmem.wen   = dmem.ren && memory_write;


    // ========================================================================
    // Response Handling
    // ========================================================================

    // CSR and error responses are captured on request acceptance.
    // Memory reads capture the registered BRAM data one state later.
    // The response remains stable until i_rsp_ready is asserted.
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            o_rsp_rdata  <= 32'b0;
            o_rsp_status <= `RSP_OK;

        end else if (request_accepted) begin
            o_rsp_rdata  <= decoded_rdata;
            o_rsp_status <= decoded_status;

        end else if (current_state == ACCESS_CAPTURE) begin
            o_rsp_rdata <= memory_imem ? imem.rdata : dmem.rdata;
        end
    end

endmodule
