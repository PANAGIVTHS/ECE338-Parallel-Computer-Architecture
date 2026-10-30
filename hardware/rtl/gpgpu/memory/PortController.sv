module PortController
    import MemorySubsystemPkg::*;
    import gpu_pkg::*;
(
    input logic clk,
    input logic rst_n,

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
    output logic bram_hold,
    output logic ddr_cand
);
    typedef enum logic [2:0] {
        IDLE,
        DDR_RD,
        BRAM_RD,
        DDR_WR,
        IMM_RSP
    } port_ctrl_state_t;

    decode_t decoded;
    assign decoded = decode(req.addr, req.write);

    port_ctrl_state_t current_state, next_state;
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
                if (req_valid && decoded.fault != MEM_OK) begin
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

            IMM_RSP: next_state = IDLE;
            default: next_state = IDLE;
        endcase
    end

    always_comb begin
        req_ready = '0;
        rsp_valid = '0;
        bram_cand = '0;
        bram_hold = '0;
        ddr_cand = '0;
        rsp.rdata = '0;
        rsp.fault = MEM_OK;

        case (current_state)
            IDLE: begin
                req_ready = 'b1;
                bram_cand = req_valid & decoded.target == TGT_BRAM & decoded.fault == MEM_OK;
            end

            BRAM_RD: begin
                bram_hold = rsp_ready;
                rsp.rdata = bram_rdata;
                rsp_valid = 1'b1;
            end

            DDR_RD: begin
                
            end

            DDR_WR: begin
                
            end

            IMM_RSP: begin
                rsp_valid = 1'b1;
                rsp.fault = decoded.fault;
            end

            default: begin end
        endcase
    end

endmodule
