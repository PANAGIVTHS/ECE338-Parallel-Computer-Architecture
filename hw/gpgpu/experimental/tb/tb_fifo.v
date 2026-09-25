`timescale 1ns/1ps
`include "../constants.vh"

module tb_fifo;

    // Parameters
    localparam WIDTH = 32;
    localparam INOUT_RATIO = 4;
    localparam DEPTH = 8;

    // Signals
    reg clk = 0;
    reg rst = 0;
    reg i_enqueue = 0;
    reg i_dequeue = 0;
    reg [(INOUT_RATIO*WIDTH)-1:0] i_data = 0;
    
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
    // TEST HELPER TASKS
    // -------------------------------------------------------------------------
    task enqueue_burst(input [WIDTH-1:0] w1, input [WIDTH-1:0] w2, input [WIDTH-1:0] w3, input [WIDTH-1:0] w4);
        begin
            @(posedge clk);
            i_enqueue <= 1'b1;
            i_dequeue <= 1'b0;
            i_data <= {w4, w3, w2, w1}; 
        end
    endtask

    task dequeue_single();
        begin
            @(posedge clk);
            i_enqueue <= 1'b0;
            i_dequeue <= 1'b1;
        end
    endtask

    task enqueue_dequeue(input [WIDTH-1:0] w1, input [WIDTH-1:0] w2, input [WIDTH-1:0] w3, input [WIDTH-1:0] w4);
        begin
            @(posedge clk);
            i_enqueue <= 1'b1;
            i_dequeue <= 1'b1;
            i_data <= {w4, w3, w2, w1};
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
    // TEST SEQUENCE
    // -------------------------------------------------------------------------
    initial begin
        $dumpfile("fifo_waves.vcd");
        $dumpvars(0, tb_fifo);

        // Initialize
        error_count = 0;
        clk = 0;
        rst = 1;
        i_enqueue = 0;
        i_dequeue = 0;
        i_data = 0;

        // Release Reset
        #15 rst = 0;
        $display("\n--- TEST START ---\n");

        // TEST 1: Basic Enqueue
        enqueue_burst(32'hAA, 32'hBB, 32'hCC, 32'hDD);
        nop();
        check_val(o_data, 32'hAA, "Enq 1: Output Data is AA");
        check_val(o_empty, 32'h0, "Enq 1: Empty flag is 0");
        check_val(o_ready_eq, 32'h1, "Enq 1: Ready flag is 1 (4 slots left)");

        // TEST 2: Basic Dequeue
        dequeue_single();
        nop();
        check_val(o_data, 32'hBB, "Deq 1: Output Data is BB");
        
        // TEST 3: Simultaneous Enqueue & Dequeue (Holds 3 items, add 4, drop 1 = 6 items)
        enqueue_dequeue(32'h11, 32'h22, 32'h33, 32'h44);
        nop();
        check_val(o_data, 32'hCC, "Enq+Deq: Output Data is CC");
        check_val(o_ready_eq, 32'h0, "Enq+Deq: Ready flag is 0 (FIFO has 6 items)");

        // TEST 4: Overfill Rejection
        enqueue_burst(32'h99, 32'h99, 32'h99, 32'h99);
        nop();
        check_val(o_op_dismissed, 32'h1, "Overfill Attempt: Operation Dismissed");
        check_val(o_data, 32'hCC, "Overfill Attempt: Data safely unchanged");

        // TEST 5: Drain the FIFO
        dequeue_single(); nop(); check_val(o_data, 32'hDD, "Drain 1"); 
        dequeue_single(); nop(); check_val(o_data, 32'h11, "Drain 2"); 
        dequeue_single(); nop(); check_val(o_data, 32'h22, "Drain 3"); 
        dequeue_single(); nop(); check_val(o_data, 32'h33, "Drain 4"); 
        dequeue_single(); nop(); check_val(o_data, 32'h44, "Drain 5"); 
        dequeue_single(); nop(); 
        check_val(o_empty, 32'h1, "Drain Complete: FIFO is Empty");

        // TEST 6: Underflow Rejection
        dequeue_single();
        nop();
        check_val(o_op_dismissed, 32'h1, "Underflow Attempt: Operation Dismissed");

        // -------------------------------------------------------------------------
        // ADVANCED EDGE CASES
        // -------------------------------------------------------------------------
        $display("\n--- ADVANCED TESTS ---");

        // TEST 7: Write Pointer Wrap-Around
        // FIFO is currently empty. wr_ptr is at row 1 (from previous tests).
        // Let's push it past its limit to force a wrap to row 0.
        enqueue_burst(32'hA1, 32'hB1, 32'hC1, 32'hD1); // wr_ptr moves to row 0 (wrap)
        nop();
        enqueue_burst(32'hA2, 32'hB2, 32'hC2, 32'hD2); // wr_ptr moves to row 1, FIFO full (8 items)
        nop();
        check_val(o_full, 32'h1, "Wrap Test: FIFO is completely full");
        check_val(o_data, 32'hA1, "Wrap Test: Front data is correct after wrap");

        // TEST 8: Read Pointer Wrap-Around & Continuous Drain
        // Drain 5 items back-to-back (no nops in between) to force rd_ptr to wrap.
        dequeue_single(); // reads A1
        dequeue_single(); // reads B1
        dequeue_single(); // reads C1
        dequeue_single(); // reads D1 (rd_ptr wraps from 7 to 0 here)
        dequeue_single(); // reads A2
        nop();
        check_val(o_data, 32'hB2, "Read Wrap: Continuous drain wrapped correctly to B2");

        // TEST 9: The "Ready_Eq" Boundary Save
        // FIFO currently has 3 items (B2, C2, D2). 
        // Dequeue 2 items so we only have 1 item left (D2).
        dequeue_single(); // reads B2
        dequeue_single(); // reads C2
        nop();
        
        // Enqueue 4 -> FIFO now has 5 items (D2, E1, E2, E3, E4).
        enqueue_burst(32'hE1, 32'hE2, 32'hE3, 32'hE4);
        nop();
        
        // Count is 5. We need 4 slots, but only 3 are free.
        check_val(o_ready_eq, 32'h0, "Boundary: Ready flag is 0 (only 3 slots left)");
        
        // Simultaneous operation should dynamically save it!
        enqueue_dequeue(32'hF1, 32'hF2, 32'hF3, 32'hF4); // Dequeues D2. Enqueues F1-F4.
        nop();
        check_val(o_op_dismissed, 32'h0, "Boundary: Simultaneous op was NOT dismissed");
        check_val(o_data, 32'hE1, "Boundary: Data correctly advanced to E1");

        // Final cleanup drain
        dequeue_single(); nop(); check_val(o_data, 32'hE2, "Drain E2");
        dequeue_single(); nop(); check_val(o_data, 32'hE3, "Drain E3");
        dequeue_single(); nop(); check_val(o_data, 32'hE4, "Drain E4");
        dequeue_single(); nop(); check_val(o_data, 32'hF1, "Drain F1");
        dequeue_single(); nop(); check_val(o_data, 32'hF2, "Drain F2");
        dequeue_single(); nop(); check_val(o_data, 32'hF3, "Drain F3");
        dequeue_single(); nop(); check_val(o_data, 32'hF4, "Drain F4");
        dequeue_single(); nop(); // Dequeues F4
        
        check_val(o_empty, 32'h1, "Final Cleanup: FIFO successfully wrapped and emptied");

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