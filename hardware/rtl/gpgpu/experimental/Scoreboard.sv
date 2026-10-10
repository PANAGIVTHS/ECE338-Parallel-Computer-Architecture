
module Scoreboard #(
    parameter DEPTH = 32,
    parameter STATE_BITS = 2
)(
    input clk,
    input rst,

    //! Write interface
    input i_op_set,
    input [ADDR_BITS-1:0] i_reg_set_addr,
    input [STATE_BITS-1:0] i_reg_state,

    //! Read interface
    input [ADDR_BITS-1:0] i_rs1_addr,
    input [ADDR_BITS-1:0] i_rs2_addr,
    input [ADDR_BITS-1:0] i_rd_addr,
    
    output reg [STATE_BITS-1:0] o_rs1_state,
    output reg [STATE_BITS-1:0] o_rs2_state,
    output reg [STATE_BITS-1:0] o_rd_state
);

    localparam ADDR_BITS = $clog2(DEPTH);

    integer i;
    reg [STATE_BITS-1:0] reg_state [0:DEPTH-1];

    always @(posedge clk or posedge rst) begin
        if (rst) begin
            for (i = 0; i < DEPTH; i = i + 1)
                reg_state[i] <= {STATE_BITS{1'b0}};
        end else if (i_op_set) begin
            reg_state[i_reg_set_addr] <= i_reg_state;
        end
    end

    //! Concurrent Reads with Forwarding
    always @(*) begin
        //! rs1 evaluation
        if (i_op_set && (i_reg_set_addr == i_rs1_addr))
            o_rs1_state = i_reg_state;
        else
            o_rs1_state = reg_state[i_rs1_addr];
            
        //! rs2 evaluation
        if (i_op_set && (i_reg_set_addr == i_rs2_addr))
            o_rs2_state = i_reg_state;
        else
            o_rs2_state = reg_state[i_rs2_addr];
            
        //! rd evaluation
        if (i_op_set && (i_reg_set_addr == i_rd_addr))
            o_rd_state = i_reg_state;
        else
            o_rd_state = reg_state[i_rd_addr];
    end

endmodule