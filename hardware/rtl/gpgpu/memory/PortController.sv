module PortController
    import MemorySubsystemPkg::*;
    import AXI4FullPkg::*;
    import DDRBackendPkg::*;
#(
    parameter bit DDR_ENABLE
) (
    input logic clk,
    input logic rst_n,
    input logic en,

    input logic rsp_ready,
    input logic req_valid,
    input mem_req_t req,

    output logic req_ready,
    output logic rsp_valid,
    output mem_rsp_t rsp,

    BRAMBackendInterface.requester bram_if,
    DDRBackendInterface.requester ddr_if,

    output logic is_idle
);
    typedef enum logic [2:0] {
        IDLE,
        DDR_RD,
        BRAM_RD,
        DDR_WR,
        IMM_RSP
    } port_ctrl_state_t;

    port_ctrl_state_t current_state, next_state;
    decode_t decoded;
    assign decoded = decode_access(req.addr, req.write, DDR_ENABLE);

    // Claim: a presented request in IDLE becomes a candidate while enabled.
    // req_ready is high only when it is actually taken (claim = issue).
    logic cand, err;
    assign cand = req_valid & (current_state == IDLE) & en;
    assign err = cand & (decoded.target == TGT_ERR);
    assign bram_if.cand = cand & (decoded.target == TGT_BRAM);
    assign ddr_if.cand = cand & (decoded.target == TGT_DDR);
    assign req_ready = err | bram_if.accept | ddr_if.accept;
    assign is_idle = current_state == IDLE;

    // IMM_RSP status, registered on entry (the decode error, or ST_OK for a
    // BRAM store) so the address decode stays off the requester's fault ->
    // stall path.
    mem_status_t status_q;
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            status_q <= ST_OK;
        end else if (err) begin
            status_q <= decoded.status;
        end else if (bram_if.accept) begin
            status_q <= ST_OK;
        end
    end

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            current_state <= IDLE;
        end else begin
            current_state <= next_state;
        end
    end

    always_comb begin
        next_state = current_state;

        case (current_state)
            IDLE: begin
                if (err) begin
                    next_state = IMM_RSP;
                end else if (bram_if.accept) begin
                    next_state = req.write ? IMM_RSP : BRAM_RD;
                end else if (ddr_if.accept) begin
                    next_state = req.write ? DDR_WR : DDR_RD;
                end

                assert ((bram_if.accept & ddr_if.accept) == 1'b0)
                else $fatal(1, "BRAM and DDR accept cannot be high at the same time");
            end

            BRAM_RD: begin
                if (rsp_ready) begin
                    next_state = IDLE;
                end
            end

            DDR_RD: begin
                if (rsp_ready && ddr_if.rd_valid) begin
                    next_state = IDLE;
                end
            end

            DDR_WR: begin
                if (rsp_ready && ddr_if.wr_valid) begin
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

    logic beat_offset;
    assign beat_offset = req.addr[WORD_SELECT_BIT];

    always_comb begin
        rsp_valid = '0;
        rsp.rdata = '0;
        rsp.status = ST_OK;
        bram_if.take = '0;
        ddr_if.is_rd_member = '0;
        ddr_if.rd_ready = '0;
        ddr_if.is_wr_member = '0;
        ddr_if.wr_ready = '0;

        case (current_state)
            BRAM_RD: begin
                bram_if.take = rsp_ready;
                rsp.rdata = bram_if.rdata;
                rsp_valid = 1'b1;
            end

            DDR_RD: begin
                rsp.rdata = beat_offset ? ddr_if.rd_beat[0] : ddr_if.rd_beat[1];
                rsp.status = axiToMemStatus(ddr_if.rd_status);
                rsp_valid = ddr_if.rd_valid;
                ddr_if.rd_ready = rsp_ready;
                ddr_if.is_rd_member = 1'b1;
            end

            DDR_WR: begin
                rsp.status = axiToMemStatus(ddr_if.wr_status);
                rsp_valid = ddr_if.wr_valid;
                ddr_if.wr_ready = rsp_ready;
                ddr_if.is_wr_member = 1'b1;
            end

            IMM_RSP: begin
                rsp_valid = 1'b1;
                rsp.status = status_q;
            end

            IDLE: begin end
            default: begin end
        endcase
    end

    always_ff @(posedge clk) begin
        if (~rst_n) begin
            ddr_if.idx <= '0;
        end else if (ddr_if.accept) begin
            ddr_if.idx <= req.write ? ddr_if.alloc_wr : ddr_if.alloc_rd;
        end
    end

endmodule
