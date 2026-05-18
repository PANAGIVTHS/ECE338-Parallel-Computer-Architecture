/*
    This is a General Use Counter module that can be used to count up to a specified number of bits.
    The counter supports a synchronous reset and a synchronous load (set) operation via the 
    i_set_reset input. An enable signal is provided; when LOW, the counter will hold its current 
    value, and when HIGH, it will increment. Reset has the highest priority, followed by the 
    set (load) operation.

    *Parameters:
    - BITS: The number of bits for the counter (default is 10 bits)
    
    ?Inputs:
    - clk: Clock input
    - i_set_reset: 2-bit control signal. 
        - Bit [1] (MSB): Synchronous reset (clears the counter to 0)
        - Bit [0] (LSB): Synchronous set (loads the value from i_count_set)
    - i_count_enable: Enable input to increment the counter
    - i_count_set: The value to load into the counter when the set signal is asserted
    
    ?Outputs:
    - o_count_cur: The current count value (BITS bits wide)
*/

module GUCounter #(
    parameter BITS = 10
)(
    input clk,
    input [1:0] i_set_reset,
    input i_count_enable,
    input [BITS-1:0] i_count_set,
    output reg [BITS-1:0] o_count_cur
);
    wire reset = i_set_reset[1]; 
    wire count_set = i_set_reset[0]; 

    initial begin
        o_count_cur <= {BITS{1'b1}};
    end

    //! Counter logic
    always @(posedge clk) begin
        if (!reset) begin
            o_count_cur <= {BITS{1'b1}};
        end else if (count_set) begin 
            o_count_cur <= i_count_set; 
        end else if (i_count_enable) begin
            o_count_cur <= o_count_cur + 1; 
        end
    end
endmodule
