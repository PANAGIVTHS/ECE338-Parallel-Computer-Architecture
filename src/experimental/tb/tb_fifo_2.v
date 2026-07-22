`timescale 1ns/1ps
`include "constants.vh"

module tb_fifo;

    // -------------------------------------------------------------------------
    // NEW PARAMETERS
    // -------------------------------------------------------------------------
    localparam WIDTH = 48;
    localparam INOUT_RATIO = 2;
    localparam DEPTH = 4;

    // Signals
    reg clk = 0; // Initialize at declaration to avoid viewer X-state rendering bugs
    reg rst;
    reg i_enqueue;
    reg i_dequeue;
    reg [(INOUT_RATIO*WIDTH)-1:0] i_data;
    
    wire [WIDTH-1:0] o_data;
    wire o_empty;
    wire o_op_dismissed;
    wire o_ready_eq;
    wire o_full;

    // Test Tracking
    integer error_count;

    // Instantiate the FIFO
    fifo #(
        .WIDTH(WIDTH),
        .INOUT_RATIO(INOUT_RATIO),
        .DEPTH(DEPTH)
    ) dut (
        .clk(clk),
        .rst(rst),
        .i_enqueue(i_enqueue),
        .i_dequeue(i_dequeue),
        .i_data(i_data),
        .o_data(o_data),
        .o_empty(o_empty),
        .o_op_dismissed(o_op_dismissed),
        .o_ready_eq(o_ready_eq),
        .o_full(o_full)
    );

    // Clock Generation (100 MHz)
    always #5 clk = ~clk;

    // -------------------------------------------------------------------------
    // UPDATED TEST HELPER TASKS (Adapted for INOUT_RATIO = 2)
    // -------------------------------------------------------------------------
    task enqueue_burst(input [WIDTH-1:0] w1, input [WIDTH-1:0] w2);
        begin
            @(posedge clk);
            i_enqueue <= 1'b1;
            i_dequeue <= 1'b0;
            i_data <= {w2, w1}; // Pack 2 items instead of 4
        end
    endtask

    task dequeue_single();
        begin
            @(posedge clk);
            i_enqueue <= 1'b0;
            i_dequeue <= 1'b1;
        end
    endtask

    task enqueue_dequeue(input [WIDTH-1:0] w1, input [WIDTH-1:0] w2);
        begin
            @(posedge clk);
            i_enqueue <= 1'b1;
            i_dequeue <= 1'b1;
            i_data <= {w2, w1};
        end
    endtask

    task nop();
        begin
            @(posedge clk);
            i_enqueue <= 1'b0;
            i_dequeue <= 1'b0;
            #1; // Wait 1 simulation tick for registers to update cleanly
        end
    endtask

    // Automated Check Task with ANSI Colors
    task check_val(input [WIDTH-1:0] actual, input [WIDTH-1:0] expected, input [80*8:1] test_name);
        begin
            if (actual !== expected) begin
                $display("\033[1;31m[FAIL]\033[0m %s | Expected: %h, Got: %h", test_name, expected, actual);
                error_count = error_count + 1;
            end else begin
                $display("\033[1;32m[PASS]\033[0m %s", test_name);
            end
        end
    endtask

    // -------------------------------------------------------------------------
    // TEST SEQUENCE (Adapted for DEPTH = 4)
    // -------------------------------------------------------------------------
    initial begin
        $dumpfile("fifo_waves.vcd");
        $dumpvars(0, tb_fifo);

        // Initialize
        error_count = 0;
        rst = 1;
        i_enqueue = 0;
        i_dequeue = 0;
        i_data = 0;

        // Release Reset
        #15 rst = 0;
        $display("\n--- TEST START (W:48, R:2, D:4) ---\n");

        // TEST 1: Basic Enqueue (Adds 2 items. FIFO is now 50% full)
        enqueue_burst(48'hAA, 48'hBB);
        nop();
        check_val(o_data, 48'hAA, "Enq 1: Output Data is AA");
        check_val(o_empty, 48'h0, "Enq 1: Empty flag is 0");
        check_val(o_ready_eq, 48'h1, "Enq 1: Ready flag is 1 (2 slots left)");

        // TEST 2: Basic Dequeue (Drops AA. 1 item left)
        dequeue_single();
        nop();
        check_val(o_data, 48'hBB, "Deq 1: Output Data is BB");
        
        // TEST 3: Simultaneous Enqueue & Dequeue (Holds 1, drops 1, adds 2 = 2 items)
        enqueue_dequeue(48'h11, 48'h22);
        nop();
        check_val(o_data, 48'h11, "Enq+Deq: Output Data is 11");
        
        // Fill the rest of the FIFO to test overfill (Adds 2 items. Total = 4. Full)
        enqueue_burst(48'h33, 48'h44);
        nop();
        check_val(o_full, 48'h1, "Fill: FIFO is completely full");

        // TEST 4: Overfill Rejection (FIFO holds 4 items, tries to add 2)
        enqueue_burst(48'h99, 48'h99);
        nop();
        check_val(o_op_dismissed, 48'h1, "Overfill Attempt: Operation Dismissed");
        check_val(o_data, 48'h11, "Overfill Attempt: Data safely unchanged (still 11)");

        // TEST 5: Drain the FIFO
        dequeue_single(); nop(); check_val(o_data, 48'h22, "Drain 1"); 
        dequeue_single(); nop(); check_val(o_data, 48'h33, "Drain 2"); 
        dequeue_single(); nop(); check_val(o_data, 48'h44, "Drain 3"); 
        dequeue_single(); nop(); 
        check_val(o_empty, 48'h1, "Drain Complete: FIFO is Empty");

        // TEST 6: Underflow Rejection
        dequeue_single();
        nop();
        check_val(o_op_dismissed, 48'h1, "Underflow Attempt: Operation Dismissed");

        // -------------------------------------------------------------------------
        // ADVANCED EDGE CASES
        // -------------------------------------------------------------------------
        $display("\n--- ADVANCED TESTS ---");

        // TEST 7: Write Pointer Wrap-Around
        // FIFO is empty. wr_ptr is at row 0.
        enqueue_burst(48'hA1, 48'hB1); // wr_ptr moves to row 1
        nop();
        enqueue_burst(48'hA2, 48'hB2); // wr_ptr wraps to row 0. FIFO full (4 items).
        nop();
        check_val(o_full, 48'h1, "Wrap Test: FIFO is completely full");
        check_val(o_data, 48'hA1, "Wrap Test: Front data is correct after wrap");

        // TEST 8: Read Pointer Wrap-Around & Continuous Drain
        // Drain 3 items to force rd_ptr near the edge.
        dequeue_single(); // reads A1
        dequeue_single(); // reads B1
        dequeue_single(); // reads A2 (rd_ptr will wrap on the NEXT read)
        nop();
        check_val(o_data, 48'hB2, "Read Wrap: Continuous drain correctly positioned at B2");

        // TEST 9: The "Ready_Eq" Boundary Save
        // FIFO currently has 1 item (B2). Depth is 4.
        
        // Enqueue 2 -> FIFO now has 3 items (B2, E1, E2). 
        enqueue_burst(48'hE1, 48'hE2);
        nop();
        
        // Count is 3. We need 2 slots, but only 1 is free (4 - 3 = 1).
        check_val(o_ready_eq, 48'h0, "Boundary: Ready flag is 0 (only 1 slot left)");
        
        // Simultaneous operation should dynamically save it!
        enqueue_dequeue(48'hF1, 48'hF2); // Dequeues B2. Enqueues F1-F2.
        nop();
        check_val(o_op_dismissed, 48'h0, "Boundary: Simultaneous op was NOT dismissed");
        check_val(o_data, 48'hE1, "Boundary: Data correctly advanced to E1");

        // Final cleanup drain
        dequeue_single(); nop(); check_val(o_data, 48'hE2, "Drain E2");
        dequeue_single(); nop(); check_val(o_data, 48'hF1, "Drain F1");
        dequeue_single(); nop(); check_val(o_data, 48'hF2, "Drain F2");
        dequeue_single(); nop(); // Dequeues F2
        
        check_val(o_empty, 48'h1, "Final Cleanup: FIFO successfully wrapped and emptied");

        // -------------------------------------------------------------------------
        // FINAL RESULTS
        // -------------------------------------------------------------------------
        if (error_count == 0) begin
            $display("\n\033[1;42;37m                                    \033[0m");
            $display("\033[1;42;37m        ALL TESTS PASSED!           \033[0m");
            $display("\033[1;42;37m                                    \033[0m\n");
        end else begin
            $display("\n\033[1;41;37m                                    \033[0m");
            $display("\033[1;41;37m        TESTS FAILED: %0d ERRORS       \033[0m", error_count);
            $display("\033[1;41;37m                                    \033[0m\n");
        end

        $finish;
    end
endmodule