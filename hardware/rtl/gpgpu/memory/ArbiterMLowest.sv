// ArbiterMLowest — select the M lowest-index set bits of an N-bit request
// vector. Reusable priority primitive: M=1 is a seed picker (DDR), M=2 is the
// BRAM two-port picker, etc.
//
// Implementation: iterative "peel" on the carry chain —
//   win_oh[m] = rem & -rem        (lowest set bit)
//   rem       = rem & (rem-1)      (clear it, feed next stage)
// M stages in series. Cheap and simple for small M (<=~4).

module ArbiterMLowest #(
    parameter int unsigned N = 32,
    parameter int unsigned M = 2,
    localparam int unsigned IDXW = (N > 1) ? $clog2(N) : 1
) (
    input logic [N-1:0] req,
    output logic [N-1:0] grant, // OR of all winners (<=M bits set)
    output logic [M-1:0][N-1:0] win_oh, // per-slot one-hot, slot 0 = lowest index
    output logic [M-1:0] win_vld, // slot m found a winner
    output logic [M-1:0][IDXW-1:0] win_idx // index of each winner
);
    // remaining request vector before each peel stage; rem[0] = req
    logic [N-1:0] rem [M+1];
    assign rem[0] = req;

    for (genvar m = 0; m < int'(M); m++) begin : g_peel
        assign win_oh[m] = rem[m] & (~rem[m] + {{N-1{1'b0}}, 1'b1}); // lowest set bit
        assign win_vld[m] = |rem[m];
        assign rem[m+1] = rem[m] & (rem[m] - {{N-1{1'b0}}, 1'b1}); // clear lowest

        // one-hot -> binary (flat OR, since win_oh[m] is one-hot)
        always_comb begin
            win_idx[m] = '0;
            for (int k = 0; k < int'(N); k++)
                if (win_oh[m][k]) win_idx[m] |= k[IDXW-1:0];
        end
    end

    // winners = the bits that got peeled = req with the M lowest cleared, inverted
    assign grant = req & ~rem[M];
endmodule
