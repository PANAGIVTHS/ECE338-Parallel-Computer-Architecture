
module stack #(
    parameter WIDTH = 32,
    parameter DEPTH = 16
)(
    input clk,
    input rst,
    input i_push,
    input i_pop,
    input [WIDTH-1:0] i_data,
    output reg [WIDTH-1:0] o_data,
    output reg o_empty,
    output reg o_full
);

    reg [WIDTH-1:0] stack [0:DEPTH-1];
    reg [$clog2(DEPTH):0] stack_ptr;

    always @(posedge clk or posedge rst) begin
        if (rst) begin
            stack_ptr <= 0;
            o_empty <= 1;
            o_full <= 0;
        end else begin
            if (i_push && !o_full) begin
                stack[stack_ptr] <= i_data;
                stack_ptr <= stack_ptr + 1;
                o_empty <= 0;

                if (stack_ptr == DEPTH - 1) begin
                    o_full <= 1;
                end

            end else if (i_pop && !o_empty) begin
                stack_ptr <= stack_ptr - 1;
                o_full <= 0;

                if (stack_ptr == 1) begin
                    o_empty <= 1;
                end
            end
        end
    end

    always @(*) begin
      if (!o_empty & i_pop)
            o_data = stack[stack_ptr - 1];
        else
            o_data = {WIDTH{1'b0}};
    end

endmodule