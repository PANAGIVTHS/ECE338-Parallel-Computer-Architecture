module PortController
    import MemorySubsystemPkg::*;
    import DDRBackendPkg::*;
    import AXI4FullPkg::*;
#(
    parameter bit DDR_ENABLE
) (
    input logic clk,
    input logic rst_n,
    input logic i_en,

    input logic i_rsp_ready,
    input logic i_req_valid,
    input mem_req_t req,

    output logic o_req_ready,
    output logic o_rsp_valid,
    output mem_rsp_t rsp,

    BRAMBackendInterface.requester bram_if,
    DDRBackendInterface.requester ddr_if,

    input beat_rdata_t i_ddr_rd_beat,
    input axi_resp_t i_ddr_rd_resp,
    input ring_index_t i_ddr_alloc,

    output logic o_idle
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
    // o_req_ready is high only when it is actually taken (claim = issue).
    logic cand, err;
    assign cand = i_req_valid & (current_state == IDLE) & i_en;
    assign err = cand & (decoded.target == TGT_ERR);
    assign bram_if.cand = cand & (decoded.target == TGT_BRAM);
    assign ddr_if.cand = cand & (decoded.target == TGT_DDR);
    assign o_req_ready = err | bram_if.accept | ddr_if.accept;
    assign o_idle = current_state == IDLE;

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
                if (i_rsp_ready) begin
                    next_state = IDLE;
                end
            end

            DDR_RD: begin
                if (i_rsp_ready && ddr_if.rd_sel) begin
                    next_state = IDLE;
                end
            end

            DDR_WR: begin
                if (i_rsp_ready && ddr_if.wr_bdone) begin
                    next_state = IDLE;
                end
            end

            IMM_RSP: begin
                if (i_rsp_ready) begin
                    next_state = IDLE;
                end
            end

            default: next_state = IDLE;
        endcase
    end

    always_comb begin
        o_rsp_valid = '0;
        rsp.rdata = '0;
        rsp.status = ST_OK;
        bram_if.take = '0;
        ddr_if.rd_member = '0;
        ddr_if.rd_take = '0;
        ddr_if.wr_member = '0;
        ddr_if.wr_take = '0;

        case (current_state)
            BRAM_RD: begin
                bram_if.take = i_rsp_ready;
                rsp.rdata = bram_if.rdata;
                o_rsp_valid = 1'b1;
            end

            DDR_RD: begin
                rsp.rdata = i_ddr_rd_beat[word_sel_of(req.addr)];
                rsp.status = axiToMemStatus(i_ddr_rd_resp);
                o_rsp_valid = ddr_if.rd_sel;
                ddr_if.rd_take = ddr_if.rd_sel & i_rsp_ready;
                ddr_if.rd_member = 1'b1;
            end

            DDR_WR: begin
                rsp.status = axiToMemStatus(ddr_if.wr_bresp);
                o_rsp_valid = ddr_if.wr_bdone;
                ddr_if.wr_take = ddr_if.wr_bdone & i_rsp_ready;
                ddr_if.wr_member = 1'b1;
            end

            IMM_RSP: begin
                o_rsp_valid = 1'b1;
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
            ddr_if.idx <= i_ddr_alloc;
        end
    end

endmodule
