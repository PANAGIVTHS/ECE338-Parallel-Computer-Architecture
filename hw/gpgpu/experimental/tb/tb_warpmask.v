`timescale 1ns/1ps

module tb_WarpStateMask;

    // Parameters
    localparam WARP_NUM = 32;
    localparam STATE_BITS = 2;
    localparam WARP_ID_BITS = $clog2(WARP_NUM);

    // Signals
    reg clk = 0;
    reg rst = 0;
    
    // Write interface
    reg i_op_set = 0;
    reg [WARP_ID_BITS-1:0] i_warp_set_id = 0;
    reg [STATE_BITS-1:0] i_warp_state = 0;

    // Read interface
    wire [(WARP_NUM * STATE_BITS)-1:0] o_all_states;

    // Test Tracking
    integer error_count;
    integer i;
    reg [(WARP_NUM * STATE_BITS)-1:0] expected_mask;

    // Instantiate the WarpStateMask
    WarpStateMask #(
        .WARP_NUM(WARP_NUM),
        .STATE_BITS(STATE_BITS)
    ) dut (
        .clk(clk),
        .rst(rst),
        .i_op_set(i_op_set),
        .i_warp_set_id(i_warp_set_id),
        .i_warp_state(i_warp_state),
        .o_all_states(o_all_states)
    );

    // Clock Generation (100 MHz)
    always #5 clk = ~clk;

    // -------------------------------------------------------------------------
    // TEST HELPER TASKS
    // -------------------------------------------------------------------------
    
    task set_warp(input [WARP_ID_BITS-1:0] id, input [STATE_BITS-1:0] state);
        begin
            @(posedge clk);
            i_op_set <= 1'b1;
            i_warp_set_id <= id;
            i_warp_state <= state;
        end
    endtask

    // Check state while asserting a write on the same cycle (forwarding check)
    task set_and_eval(input [WARP_ID_BITS-1:0] s_id, input [STATE_BITS-1:0] s_state);
        begin
            @(posedge clk);
            i_op_set <= 1'b1;
            i_warp_set_id <= s_id;
            i_warp_state <= s_state;
            #1; // Wait 1 tick for combinational forwarding to settle
        end
    endtask

    task nop();
        begin
            @(posedge clk);
            i_op_set <= 1'b0;
            #1;
        end
    endtask

    task check_val(input [STATE_BITS-1:0] actual, input [STATE_BITS-1:0] expected, input [80*8:1] test_name);
        begin
            if (actual !== expected) begin
                $display("\033[1;31m[FAIL]\033[0m %s | Expected: %h, Got: %h", test_name, expected, actual);
                error_count = error_count + 1;
            end else begin
                $display("\033[1;32m[PASS]\033[0m %s", test_name);
            end
        end
    endtask

    task check_full(input [(WARP_NUM*STATE_BITS)-1:0] actual, input [(WARP_NUM*STATE_BITS)-1:0] expected, input [80*8:1] test_name);
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
        $dumpfile("warp_mask_waves.vcd");
        $dumpvars(0, tb_WarpStateMask);

        error_count = 0;
        clk = 0;
        rst = 1;
        
        i_op_set = 0;
        i_warp_set_id = 0;
        i_warp_state = 0;

        #15 rst = 0;
        $display("\n--- TEST START ---\n");

        // TEST 1: Check Reset State
        nop();
        check_full(o_all_states, 64'b0, "Reset: Full mask is perfectly clear");

        // TEST 2: Basic Set and Read
        set_warp(5'd3, 2'b01); // Mark Warp 3 as ACTIVE
        nop();
        check_val(o_all_states[7:6], 2'b01, "Basic Write: Warp 3 correctly updated");

        // TEST 3: Forwarding on Flattened Array
        set_and_eval(5'd10, 2'b11);
        check_val(o_all_states[21:20], 2'b11, "Forwarding: Bypass active for Warp 10 in full mask");

        // TEST 4: Non-destructive Write
        set_warp(5'd15, 2'b10);
        nop();
        check_val(o_all_states[31:30], 2'b10, "Retention: Warp 15 correctly updated");
        check_val(o_all_states[7:6], 2'b01, "Retention: Warp 3 retained state");
        check_val(o_all_states[21:20], 2'b11, "Retention: Warp 10 retained state");

        // TEST 5: Overwrite
        set_warp(5'd3, 2'b00); // Clear Warp 3
        nop();
        check_val(o_all_states[7:6], 2'b00, "Overwrite: Warp 3 cleared successfully");

        $display("\n--- ADVANCED TESTS ---");

        // TEST 6: Boundary Warps (W0 and W31)
        set_warp(5'd0, 2'b01);
        set_warp(5'd31, 2'b10);
        nop();
        check_val(o_all_states[1:0], 2'b01, "Boundary: Warp 0 correctly written");
        check_val(o_all_states[63:62], 2'b10, "Boundary: Warp 31 correctly written");

        // TEST 7: Saturated Array Pattern (All 11s)
        for (i = 0; i < WARP_NUM; i = i + 1) begin
            set_warp(i[WARP_ID_BITS-1:0], 2'b11);
        end
        nop();
        expected_mask = {WARP_NUM{2'b11}};
        check_full(o_all_states, expected_mask, "Saturation: Entire mask holds 2'b11");

        // TEST 8: Checkerboard Pattern (Ensure no adjacent bit bleeding)
        // Even Warps = 2'b01, Odd Warps = 2'b10
        expected_mask = 0;
        for (i = 0; i < WARP_NUM; i = i + 1) begin
            if (i % 2 == 0) begin
                set_warp(i[WARP_ID_BITS-1:0], 2'b01);
                expected_mask[(i*STATE_BITS) +: STATE_BITS] = 2'b01;
            end else begin
                set_warp(i[WARP_ID_BITS-1:0], 2'b10);
                expected_mask[(i*STATE_BITS) +: STATE_BITS] = 2'b10;
            end
        end
        nop();
        check_full(o_all_states, expected_mask, "Checkerboard: Alternating states applied flawlessly");

        // TEST 9: Forwarding during Checkerboard Context
        // Overwrite Warp 16 (even) to 2'b11 and check immediately
        expected_mask[(16*STATE_BITS) +: STATE_BITS] = 2'b11;
        set_and_eval(5'd16, 2'b11);
        check_full(o_all_states, expected_mask, "Forwarding + Complex Context: W16 bypassed while retaining checkerboard");

        // TEST 10: Mid-flight Reset Recovery
        // Let the write commit, then blast the array with reset
        nop();
        @(posedge clk);
        rst <= 1'b1;
        #1; // Look at combinational output immediately after reset latches
        check_full(o_all_states, 64'b0, "Reset Recovery: Full mask instantly cleared on reset");
        rst <= 1'b0;

        // -------------------------------------------------------------------------
        // FINAL RESULTS
        // -------------------------------------------------------------------------
        if (error_count == 0) begin
            $display("\n\033[1;42;37m                                    \033[0m");
            $display("\033[1;42;37m        ALL TESTS PASSED!           \033[0m");
            $display("\033[1;42;37m                                    \033[0m\n");
        end else begin
            $display("\n\033[1;41;37m                                    \033[0m");
            $display("\033[1;41;37m        TESTS FAILED: %0d ERRORS      \033[0m", error_count);
            $display("\033[1;41;37m                                    \033[0m\n");
        end

        $finish;
    end
endmodule