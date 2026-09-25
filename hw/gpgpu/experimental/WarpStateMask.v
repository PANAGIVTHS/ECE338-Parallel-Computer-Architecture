module WarpStateMask #(
    parameter WARP_NUM = 32,
    parameter STATE_BITS = 2
)(
    input clk,
    input rst,

    //! Write interface
    input i_op_set,
    input [WARP_ID_BITS-1:0] i_warp_set_id,
    input [STATE_BITS-1:0] i_warp_state,

    //! Flattened Read Port
    output [(WARP_NUM * STATE_BITS)-1:0] o_all_states
);

    localparam WARP_ID_BITS = $clog2(WARP_NUM);

    integer i;
    reg [STATE_BITS-1:0] warp_state [0:WARP_NUM-1];

    always @(posedge clk or posedge rst) begin
        if (rst) begin
            for (i = 0; i < WARP_NUM; i = i + 1)
                warp_state[i] <= {STATE_BITS{1'b0}};
        end else if (i_op_set) begin
            warp_state[i_warp_set_id] <= i_warp_state;
        end
    end

    genvar g;
    generate
        for (g = 0; g < WARP_NUM; g = g + 1) begin : gen_flatten
            assign o_all_states[(g * STATE_BITS) +: STATE_BITS] = 
                (i_op_set && (i_warp_set_id == g)) ? i_warp_state : warp_state[g];
        end
    endgenerate

endmodule