`timescale 1ns / 1ps

`include "stack.v"

module tb_stack();

    // Parameters
    parameter WIDTH = 32;
    parameter DEPTH = 16;

    // Testbench Signals
    reg clk;
    reg rst;
    reg i_push;
    reg i_pop;
    reg [WIDTH-1:0] i_data;
    
    wire [WIDTH-1:0] o_data;
    wire o_empty;
    wire o_full;

    // Instantiate the Device Under Test (DUT)
    stack #(
        .WIDTH(WIDTH),
        .DEPTH(DEPTH)
    ) dut (
        .clk(clk),
        .rst(rst),
        .i_push(i_push),
        .i_pop(i_pop),
        .i_data(i_data),
        .o_data(o_data),
        .o_empty(o_empty),
        .o_full(o_full)
    );

    // Clock Generation (100MHz / 10ns period)
    always #5 clk = ~clk;

    // ---------------------------------------------------------
    // TASK: Dump and display the entire stack state
    // ---------------------------------------------------------
    task print_stack_state;
        integer i;
        begin
            $display("==================================================");
            $display("Time: %0t | Ptr: %0d | Empty: %b | Full: %b", 
                     $time, dut.stack_ptr, o_empty, o_full);
            $display("Output o_data: 0x%0h", o_data);
            $display("--- Internal Memory State ---");
            
            if (o_empty) begin
                $display("  [Stack is completely empty]");
            end else begin
                // Loop through and print only the valid entries in the stack
                for (i = 0; i < dut.stack_ptr; i = i + 1) begin
                    if (i == dut.stack_ptr - 1)
                        $display("  stack[%0d] = 0x%0h  <-- TOP", i, dut.stack[i]);
                    else
                        $display("  stack[%0d] = 0x%0h", i, dut.stack[i]);
                end
            end
            $display("==================================================\n");
        end
    endtask

    // ---------------------------------------------------------
    // Main Test Sequence
    // ---------------------------------------------------------
    initial begin
        // Initialize signals
        clk = 0;
        rst = 0;
        i_push = 0;
        i_pop = 0;
        i_data = 0;

        // Apply Reset
        $display("Applying Reset...");
        rst = 1;
        #20;
        rst = 0;
        #10;
        
        $display("State after Reset:");
        print_stack_state();

        // Push 3 values onto the stack
        $display("Pushing 3 values (0xAA, 0xBB, 0xCC)...");
        @(posedge clk);
        i_push = 1; i_data = 32'h000000AA; @(posedge clk);
        i_push = 1; i_data = 32'h000000BB; @(posedge clk);
        i_push = 1; i_data = 32'h000000CC; @(posedge clk);
        i_push = 0; 
        print_stack_state();

        // Pop 1 value off the stack
        $display("Popping 1 value...");
        @(posedge clk);
        i_pop = 1; @(posedge clk);
        i_pop = 0;
        print_stack_state();

        // Fill the stack to test the o_full flag
        $display("Filling the rest of the stack...");
        i_push = 1;
        // The stack currently has 2 items. We need to push 14 more to fill it (Depth = 16).
        for (integer j = 2; j < DEPTH; j = j + 1) begin
            i_data = j * 32'h11111111; // Generate dummy data
            @(posedge clk);
        end
        i_push = 0;
        @(posedge clk);
        print_stack_state();

        // Try to push while full (should be ignored by your logic)
        $display("Attempting to push while full...");
        @(posedge clk);
        i_push = 1; i_data = 32'hDEADBEEF; @(posedge clk);
        i_push = 0;
        print_stack_state();

        // Empty the stack completely
        $display("Popping all values to empty the stack...");
        i_pop = 1;
        for (integer k = 0; k < DEPTH; k = k + 1) begin
            @(posedge clk);
        end
        i_pop = 0;
        @(posedge clk);
        print_stack_state();

        $display("Simulation Complete.");
        $finish;
    end

endmodule