module InstrFetch (
    input clk,
    input rst,
    input [31:0] i_program_counter,
    output [31:0] o_fetched_instr
);

    // Create a dummy ROM and tell Vivado absolutely not to optimize it
    (* dont_touch = "true" *) reg [31:0] instr_mem [0:63];

    // Initialize the memory
    integer i;
    initial begin
        for (i = 0; i < 64; i = i + 1) begin
            // Fill with standard NOPs (addi x0, x0, 0)
            instr_mem[i] = 32'h00000013; 
        end
    end

    assign o_fetched_instr = instr_mem[i_program_counter[7:2]];

endmodule