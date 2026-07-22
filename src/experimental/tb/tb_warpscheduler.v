`timescale 1ns/1ps

module tb_WarpScheduler;

    // Parameters
    localparam WARP_NUM = 32;
    localparam SLOTS = 2;
    localparam STATE_BITS = 2;
    localparam READY_STATE = 2'b01;
    localparam WARP_ID_BITS = $clog2(WARP_NUM);

    // Signals
    reg clk = 0;
    reg rst = 0;
    
    reg [(WARP_NUM * STATE_BITS)-1:0] i_all_states = 0;

    wire [SLOTS-1:0] o_valid;
    wire [(SLOTS * WARP_ID_BITS)-1:0] o_winner_id;

    // Test Tracking
    integer error_count;
    integer i;

    // Instantiate the Scheduler
    WarpScheduler #(
        .WARP_NUM(WARP_NUM),
        .SLOTS(SLOTS),
        .STATE_BITS(STATE_BITS),
        .READY_STATE(READY_STATE)
    ) dut (
        .clk(clk),
        .rst(rst),
        .i_all_states(i_all_states),
        .o_valid(o_valid),
        .o_winner_id(o_winner_id)
    );

    // Clock Generation (100 MHz)
    always #5 clk = ~clk;

    // -------------------------------------------------------------------------
    // TEST HELPER TASKS & FUNCTIONS
    // -------------------------------------------------------------------------
    
    function [(WARP_NUM * STATE_BITS)-1:0] build_states;
        input [WARP_NUM-1:0] ready_mask;
        integer k;
        begin
            build_states = 0;
            for (k = 0; k < WARP_NUM; k = k + 1) begin
                if (ready_mask[k])
                    build_states[(k * STATE_BITS) +: STATE_BITS] = READY_STATE;
                else
                    build_states[(k * STATE_BITS) +: STATE_BITS] = 2'b00; // Idle
            end
        end
    endfunction

    task set_ready_mask(input [WARP_NUM-1:0] ready_mask);
        begin
            i_all_states = build_states(ready_mask);
            #1; // Wait 1 tick for combinational evaluation
        end
    endtask

    // Allows manually setting a specific state to test non-ready rejection
    task set_custom_state(input integer warp_idx, input [STATE_BITS-1:0] state);
        begin
            i_all_states[(warp_idx * STATE_BITS) +: STATE_BITS] = state;
            #1;
        end
    endtask

    task tick();
        begin
            @(posedge clk);
            #1; // Sample just after the clock edge
        end
    endtask

    task check_slot(input integer slot, input exp_valid, input [WARP_ID_BITS-1:0] exp_id, input [80*8:1] test_name);
        reg actual_valid;
        reg [WARP_ID_BITS-1:0] actual_id;
        begin
            actual_valid = o_valid[slot];
            actual_id = o_winner_id[(slot * WARP_ID_BITS) +: WARP_ID_BITS];

            if (actual_valid !== exp_valid || (exp_valid && actual_id !== exp_id)) begin
                $display("\033[1;31m[FAIL]\033[0m %s | Expected: V=%b, ID=%0d | Got: V=%b, ID=%0d", 
                         test_name, exp_valid, exp_id, actual_valid, actual_id);
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
        $dumpfile("warpscheduler_waves.vcd");
        $dumpvars(0, tb_WarpScheduler);

        error_count = 0;
        clk = 0;
        rst = 1;
        i_all_states = 0;

        #15 rst = 0;
        $display("\n--- CORE MECHANICS TESTS ---\n");

        // TEST 1: Check Reset / Empty State
        set_ready_mask(32'h0000_0000);
        check_slot(0, 1'b0, 5'd0, "Idle: Slot 0 Invalid");
        check_slot(1, 1'b0, 5'd0, "Idle: Slot 1 Invalid");

        // TEST 2: Single Warp Ready
        set_ready_mask(32'h0000_0020); // Bit 5 is 1
        check_slot(0, 1'b1, 5'd5, "Single: Slot 0 selected Warp 5");
        check_slot(1, 1'b0, 5'd0, "Single: Slot 1 is Invalid");
        tick();

        // TEST 3: Multi-Warp & Epoch Persistence
        set_ready_mask(32'h0000_1420); // Bits 5, 10, 12
        check_slot(0, 1'b1, 5'd10, "Persistence: Slot 0 selected Warp 10 (lowest w/ ticket)");
        check_slot(1, 1'b1, 5'd12, "Persistence: Slot 1 selected Warp 12");
        tick(); 

        check_slot(0, 1'b1, 5'd5,  "Epoch Refill: Tickets restored! Slot 0 selects Warp 5");
        check_slot(1, 1'b1, 5'd10, "Epoch Refill: Slot 1 selects Warp 10");
        tick();

        $display("\n--- EDGE CASE & STRESS TESTS ---");

        // TEST 4: The Mid-Cycle Epoch Refill
        set_ready_mask(32'h0000_0000);
        rst = 1; tick(); rst = 0; tick();
        
        set_ready_mask(32'h0000_0080); // Bit 7 goes first, spends ticket
        check_slot(0, 1'b1, 5'd7, "Mid-Cycle Prep: Warp 7 spends ticket");
        tick();

        set_ready_mask(32'h0000_0180); // Bits 7 and 8 ready
        check_slot(0, 1'b1, 5'd8, "Mid-Cycle Action: Slot 0 takes last ticket (Warp 8)");
        check_slot(1, 1'b1, 5'd7, "Mid-Cycle Action: Instant refill! Slot 1 takes Warp 7");
        tick();

        // TEST 5: Full Saturation (All 32 Warps Ready)
        $display("\n--- SATURATION TEST ---");
        set_ready_mask(32'h0000_0000);
        rst = 1; tick(); rst = 0; tick();
        
        set_ready_mask(32'hFFFF_FFFF); 

        for (i = 0; i < 16; i = i + 1) begin
            check_slot(0, 1'b1, (i*2),     "Saturation check for Slot 0");
            check_slot(1, 1'b1, (i*2) + 1, "Saturation check for Slot 1");
            tick();
        end

        check_slot(0, 1'b1, 5'd0, "Saturation Wrap: Slot 0 = 0");
        check_slot(1, 1'b1, 5'd1, "Saturation Wrap: Slot 1 = 1");

        // TEST 6: Sparse Boundary Test (Edges of the array)
        $display("\n--- SPARSE BOUNDARY TEST ---");
        set_ready_mask(32'h0000_0000);
        rst = 1; tick(); rst = 0; tick();

        set_ready_mask(32'h8000_0001); // Only Warp 0 and Warp 31 are ready
        check_slot(0, 1'b1, 5'd0,  "Sparse: Slot 0 gets Warp 0");
        check_slot(1, 1'b1, 5'd31, "Sparse: Slot 1 gets Warp 31");
        tick();
        
        // They should instantly repeat because the epoch refills immediately
        check_slot(0, 1'b1, 5'd0,  "Sparse Wrap: Slot 0 gets Warp 0");
        check_slot(1, 1'b1, 5'd31, "Sparse Wrap: Slot 1 gets Warp 31");
        tick();

        // TEST 7: Odd-Modulo Continuous Load (3 Warps, 2 Slots)
        // This is brutal for the epoch logic. The refill must shift slots every cycle.
        $display("\n--- ODD-MODULO CONTINUOUS LOAD ---");
        set_ready_mask(32'h0000_0000);
        rst = 1; tick(); rst = 0; tick();

        set_ready_mask(32'h0000_000E); // Warps 1, 2, 3 are ready continually
        
        // Cycle 1: 1 and 2 spend tickets. (3 still has a ticket)
        check_slot(0, 1'b1, 5'd1, "Odd-Mod C1: Slot 0 gets 1");
        check_slot(1, 1'b1, 5'd2, "Odd-Mod C1: Slot 1 gets 2");
        tick();

        // Cycle 2: 3 spends its ticket in Slot 0. Tickets run out! 
        // Mid-cycle refill triggers! Slot 1 gets Warp 1.
        check_slot(0, 1'b1, 5'd3, "Odd-Mod C2: Slot 0 gets 3 (Last Ticket)");
        check_slot(1, 1'b1, 5'd1, "Odd-Mod C2: Slot 1 gets 1 (Epoch Refilled Mid-Cycle!)");
        tick();

        // Cycle 3: 2 and 3 spend their newly refilled tickets.
        check_slot(0, 1'b1, 5'd2, "Odd-Mod C3: Slot 0 gets 2");
        check_slot(1, 1'b1, 5'd3, "Odd-Mod C3: Slot 1 gets 3");
        tick();

        // TEST 8: Non-Ready State Rejection
        $display("\n--- INVALID STATE REJECTION ---");
        set_ready_mask(32'h0000_0000);
        rst = 1; tick(); rst = 0; tick();

        // Let's set Warp 0 to 2'b10 (Wait/Blocked), Warp 1 to READY, Warp 2 to 2'b11 (Halt)
        set_custom_state(0, 2'b10); // Not ready
        set_custom_state(1, 2'b01); // Ready!
        set_custom_state(2, 2'b11); // Not ready
        
        // Despite 0 being the highest priority, it should be ignored.
        check_slot(0, 1'b1, 5'd1, "Rejection: Slot 0 bypasses W0/W2 and picks W1");
        check_slot(1, 1'b0, 5'd0, "Rejection: Slot 1 remains invalid");

        // -------------------------------------------------------------------------
        // FINAL RESULTS
        // -------------------------------------------------------------------------
        if (error_count == 0) begin
            $display("\n\033[1;42;37m                                    \033[0m");
            $display("\033[1;42;37m         ALL TESTS PASSED!          \033[0m");
            $display("\033[1;42;37m                                    \033[0m\n");
        end else begin
            $display("\n\033[1;41;37m                                    \033[0m");
            $display("\033[1;41;37m       TESTS FAILED: %0d ERRORS      \033[0m", error_count);
            $display("\033[1;41;37m                                    \033[0m\n");
        end

        $finish;
    end
endmodule