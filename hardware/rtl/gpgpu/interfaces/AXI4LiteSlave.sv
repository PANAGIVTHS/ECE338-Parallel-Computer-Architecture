`timescale 1 ns / 1 ps

// AXI4-Lite slave to the existing GPGPU request/response interface.
// Single outstanding transaction; AXI and GPU use the same clock/reset.
// Supported configuration: 32-bit data bus, 16-bit byte-address bus.
module gpgpu_axi_slave_lite_v1_0_S00_AXI #(
    parameter integer C_S_AXI_DATA_WIDTH = 32,
    parameter integer C_S_AXI_ADDR_WIDTH = 16
) (
    // GPU request
    output wire        o_req_valid,
    input  wire        i_req_ready,
    output wire        o_req_write,
    output wire [31:0] o_req_addr,
    output wire [31:0] o_req_wdata,
    output wire [3:0]  o_req_wstrb,

    // GPU response
    input  wire        i_rsp_valid,
    output wire        o_rsp_ready,
    input  wire [31:0] i_rsp_rdata,
    input  wire [2:0]  i_rsp_status,

    // AXI4-Lite slave
    input  wire                         S_AXI_ACLK,
    input  wire                         S_AXI_ARESETN,
    input  wire [C_S_AXI_ADDR_WIDTH-1:0] S_AXI_AWADDR,
    input  wire [2:0]                   S_AXI_AWPROT,
    input  wire                         S_AXI_AWVALID,
    output wire                         S_AXI_AWREADY,
    input  wire [C_S_AXI_DATA_WIDTH-1:0] S_AXI_WDATA,
    input  wire [C_S_AXI_DATA_WIDTH/8-1:0] S_AXI_WSTRB,
    input  wire                         S_AXI_WVALID,
    output wire                         S_AXI_WREADY,
    output wire [1:0]                   S_AXI_BRESP,
    output wire                         S_AXI_BVALID,
    input  wire                         S_AXI_BREADY,
    input  wire [C_S_AXI_ADDR_WIDTH-1:0] S_AXI_ARADDR,
    input  wire [2:0]                   S_AXI_ARPROT,
    input  wire                         S_AXI_ARVALID,
    output wire                         S_AXI_ARREADY,
    output wire [C_S_AXI_DATA_WIDTH-1:0] S_AXI_RDATA,
    output wire [1:0]                   S_AXI_RRESP,
    output wire                         S_AXI_RVALID,
    input  wire                         S_AXI_RREADY
);

    // ========================================================================
    // Transaction Control
    // ========================================================================

    localparam [2:0]
        COLLECT_WRITE = 3'd0,
        ACCEPT_READ   = 3'd1,
        GPU_REQUEST   = 3'd2,
        GPU_RESPONSE  = 3'd3,
        AXI_RESPONSE  = 3'd4;

    reg [2:0] state;
    reg       write_request;

    // ========================================================================
    // AXI Request Capture
    // ========================================================================

    reg aw_captured;
    reg w_captured;
    reg [C_S_AXI_ADDR_WIDTH-1:0] awaddr_reg;
    reg [C_S_AXI_ADDR_WIDTH-1:0] araddr_reg;
    reg [31:0] wdata_reg;
    reg [3:0]  wstrb_reg;

    // Address and data are independently acknowledged and buffered.
    // A read is granted only while no write is partially collected.
    // All READY outputs depend on registered state, not on VALID inputs.
    assign S_AXI_AWREADY = S_AXI_ARESETN &&
                           (state == COLLECT_WRITE) && !aw_captured;
    assign S_AXI_WREADY  = S_AXI_ARESETN &&
                           (state == COLLECT_WRITE) && !w_captured;
    assign S_AXI_ARREADY = S_AXI_ARESETN && (state == ACCEPT_READ);

    wire aw_fire = S_AXI_AWVALID && S_AXI_AWREADY;
    wire w_fire  = S_AXI_WVALID  && S_AXI_WREADY;
    wire ar_fire = S_AXI_ARVALID && S_AXI_ARREADY;

    // ========================================================================
    // GPU Request / Response
    // ========================================================================

    assign o_req_valid = S_AXI_ARESETN && (state == GPU_REQUEST);
    assign o_req_write = write_request;
    assign o_req_addr = {
        16'b0,
        write_request ? awaddr_reg[15:0] : araddr_reg[15:0]
    };
    assign o_req_wdata = wdata_reg;
    assign o_req_wstrb = write_request ? wstrb_reg : 4'b0000;

    assign o_rsp_ready = S_AXI_ARESETN && (state == GPU_RESPONSE);

    // ========================================================================
    // AXI Response
    // ========================================================================

    reg [1:0]  response_reg;
    reg [31:0] rdata_reg;

    function [1:0] axi_response_code;
        input [2:0] gpu_status;
        begin
            case (gpu_status)
                3'b000:  axi_response_code = 2'b00; // OKAY
                3'b001:  axi_response_code = 2'b11; // DECERR
                default: axi_response_code = 2'b10; // SLVERR
            endcase
        end
    endfunction

    assign S_AXI_BVALID = S_AXI_ARESETN &&
                          (state == AXI_RESPONSE) && write_request;
    assign S_AXI_BRESP  = response_reg;
    assign S_AXI_RVALID = S_AXI_ARESETN &&
                          (state == AXI_RESPONSE) && !write_request;
    assign S_AXI_RRESP  = response_reg;
    assign S_AXI_RDATA  = rdata_reg;

    // ========================================================================
    // Transaction State Machine
    // ========================================================================

    always @(posedge S_AXI_ACLK) begin
        if (!S_AXI_ARESETN) begin
            state         <= COLLECT_WRITE;
            write_request <= 1'b0;
            aw_captured   <= 1'b0;
            w_captured    <= 1'b0;
            awaddr_reg    <= {C_S_AXI_ADDR_WIDTH{1'b0}};
            araddr_reg    <= {C_S_AXI_ADDR_WIDTH{1'b0}};
            wdata_reg     <= 32'b0;
            wstrb_reg     <= 4'b0;
            response_reg  <= 2'b00;
            rdata_reg     <= 32'b0;
        end else begin
            case (state)
                COLLECT_WRITE: begin
                    if (aw_fire) begin
                        awaddr_reg  <= S_AXI_AWADDR;
                        aw_captured <= 1'b1;
                    end
                    if (w_fire) begin
                        wdata_reg  <= S_AXI_WDATA;
                        wstrb_reg  <= S_AXI_WSTRB;
                        w_captured <= 1'b1;
                    end

                    // Both halves may arrive in the same or different cycles.
                    if ((aw_captured || aw_fire) &&
                        (w_captured  || w_fire)) begin
                        write_request <= 1'b1;
                        state <= GPU_REQUEST;
                    end else if (!aw_captured && !w_captured &&
                                 !S_AXI_AWVALID && !S_AXI_WVALID &&
                                  S_AXI_ARVALID) begin
                        // Give an idle read its own address handshake cycle.
                        state <= ACCEPT_READ;
                    end
                end

                ACCEPT_READ: begin
                    if (ar_fire) begin
                        araddr_reg    <= S_AXI_ARADDR;
                        write_request <= 1'b0;
                        state         <= GPU_REQUEST;
                    end
                end

                GPU_REQUEST: begin
                    if (i_req_ready)
                        state <= GPU_RESPONSE;
                end

                GPU_RESPONSE: begin
                    if (i_rsp_valid) begin
                        response_reg <= axi_response_code(i_rsp_status);
                        rdata_reg    <= i_rsp_rdata;
                        state        <= AXI_RESPONSE;
                    end
                end

                AXI_RESPONSE: begin
                    if ((write_request  && S_AXI_BREADY) ||
                        (!write_request && S_AXI_RREADY)) begin
                        aw_captured <= 1'b0;
                        w_captured  <= 1'b0;
                        state       <= COLLECT_WRITE;
                    end
                end

                default: state <= COLLECT_WRITE;
            endcase
        end
    end

    // AWPROT/ARPROT are intentionally ignored; no privilege separation.
endmodule