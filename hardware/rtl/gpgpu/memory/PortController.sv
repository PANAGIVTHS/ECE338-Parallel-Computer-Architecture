module PortController
    import MemorySubsystemPkg::*;
    import gpu_pkg::*;
#(
    parameter bit DDR_ENABLE
) (
    input logic clk,
    input logic rst_n,
    input logic en,

    input logic rsp_ready,
    input logic req_valid,
    input mem_req_t req,

    input logic bram_accept,
    input word_t bram_rdata,
    input logic ddr_accept,

    output logic req_ready,
    output logic rsp_valid,
    output mem_rsp_t rsp,

    output logic bram_cand,
    output logic bram_take,
    output logic ddr_cand,
    output logic is_idle
);
    typedef enum logic [2:0] {
        IDLE,
        DDR_RD,
        BRAM_RD,
        DDR_WR,
        IMM_RSP
    } port_ctrl_state_t;

    decode_t decoded;
    assign decoded = decode_access(req.addr, req.write, DDR_ENABLE);

    port_ctrl_state_t current_state, next_state;
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            current_state <= IDLE;
        end else begin
            current_state <= next_state;
        end
    end

    // IMM_RSP status, registered on entry (the decode error, or ST_OK for a
    // BRAM store) so the address decode stays off the requester's fault ->
    // stall path.
    mem_status_t status_q;
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            status_q <= ST_OK;
        end else if (err) begin
            status_q <= decoded.status;
        end else if (bram_accept) begin
            status_q <= ST_OK;
        end
    end

    // Claim: a presented request in IDLE becomes a candidate while enabled.
    // req_ready is high only when it is actually taken (claim = issue).
    logic cand, err;
    assign cand = req_valid & (current_state == IDLE) & en;
    assign err = cand & (decoded.target == TGT_ERR);
    assign bram_cand = cand & (decoded.target == TGT_BRAM);
    assign ddr_cand = cand & (decoded.target == TGT_DDR);
    assign req_ready = err | bram_accept | ddr_accept;
    assign is_idle = current_state == IDLE;

    always_comb begin
        next_state = current_state;

        case (current_state)
            IDLE: begin
                if (err) begin
                    next_state = IMM_RSP;
                end else if (bram_accept) begin
                    next_state = req.write ? IMM_RSP : BRAM_RD;
                end else if (ddr_accept) begin
                    next_state = req.write ? DDR_WR : DDR_RD;
                end

                assert ((bram_accept & ddr_accept) == 1'b0)
                else $fatal(1, "BRAM and DDR accept cannot be high at the same time");
            end

            BRAM_RD: begin
                if (rsp_ready) begin
                    next_state = IDLE;
                end
            end

            DDR_RD: begin
                if (rsp_ready && 1'b1 /* TODO: CHECK FOR VALID DDR OUTPUT */) begin
                    next_state = IDLE;
                end
            end

            DDR_WR: begin
                if (rsp_ready && 1'b1 /* TODO: CHECK FOR VALID DDR OUTPUT */) begin
                    next_state = IDLE;
                end
            end

            IMM_RSP: begin
                if (rsp_ready) begin
                    next_state = IDLE;
                end
            end

            default: next_state = IDLE;
        endcase
    end

    always_comb begin
        rsp_valid = '0;
        bram_take = '0;
        rsp.rdata = '0;
        rsp.status = ST_OK;

        case (current_state)
            BRAM_RD: begin
                bram_take = rsp_ready;
                rsp.rdata = bram_rdata;
                rsp_valid = 1'b1;
            end

            DDR_RD: begin

            end

            DDR_WR: begin

            end

            IMM_RSP: begin
                rsp_valid = 1'b1;
                rsp.status = status_q;
            end

            default: begin end
        endcase
    end

endmodule
