`timescale 1ns/1ps

module tb_scoreboard;

    // Parameters
    localparam DEPTH = 32;
    localparam STATE_BITS = 2;
    localparam ADDR_BITS = $clog2(DEPTH);

    // Signals
    reg clk = 0;
    reg rst = 0;
    
    // Write interface
    reg i_op_set = 0;
    reg [ADDR_BITS-1:0] i_reg_set_addr = 0;
    reg [STATE_BITS-1:0] i_reg_state = 0;

    // Read interface
    reg [ADDR_BITS-1:0] i_rs1_addr = 0;
    reg [ADDR_BITS-1:0] i_rs2_addr = 0;
    reg [ADDR_BITS-1:0] i_rd_addr = 0;
    
    wire [STATE_BITS-1:0] o_rs1_state;
    wire [STATE_BITS-1:0] o_rs2_state;
    wire [STATE_BITS-1:0] o_rd_state;

    // Test Tracking
    integer error_count;
    integer i;

    // Instantiate the Scoreboard
    Scoreboard #(
        .DEPTH(DEPTH),
        .STATE_BITS(STATE_BITS)
    ) dut (
        .clk(clk),
        .rst(rst),
        .i_op_set(i_op_set),
        .i_reg_set_addr(i_reg_set_addr),
        .i_reg_state(i_reg_state),
        .i_rs1_addr(i_rs1_addr),
        .i_rs2_addr(i_rs2_addr),
        .i_rd_addr(i_rd_addr),
        .o_rs1_state(o_rs1_state),
        .o_rs2_state(o_rs2_state),
        .o_rd_state(o_rd_state)
    );

    // Clock Generation (100 MHz)
    always #5 clk = ~clk;

    // -------------------------------------------------------------------------
    // TEST HELPER TASKS
    // -------------------------------------------------------------------------
    
    // Issue a write on the next clock edge
    task set_reg(input [ADDR_BITS-1:0] addr, input [STATE_BITS-1:0] state);
        begin
            @(posedge clk);
            i_op_set <= 1'b1;
            i_reg_set_addr <= addr;
            i_reg_state <= state;
        end
    endtask

    // Evaluate 3 registers combinationally
    task eval_regs(input [ADDR_BITS-1:0] rs1, input [ADDR_BITS-1:0] rs2, input [ADDR_BITS-1:0] rd);
        begin
            @(posedge clk);
            i_op_set <= 1'b0; // Ensure no write is happening
            i_rs1_addr <= rs1;
            i_rs2_addr <= rs2;
            i_rd_addr <= rd;
            #1; // Wait 1 tick for combinational reads to settle
        end
    endtask

    // Issue a write AND evaluate registers on the same clock edge (Tests forwarding)
    task set_and_eval(
        input [ADDR_BITS-1:0] s_addr, input [STATE_BITS-1:0] s_state, 
        input [ADDR_BITS-1:0] rs1, input [ADDR_BITS-1:0] rs2, input [ADDR_BITS-1:0] rd
    );
        begin
            @(posedge clk);
            i_op_set <= 1'b1;
            i_reg_set_addr <= s_addr;
            i_reg_state <= s_state;
            
            i_rs1_addr <= rs1;
            i_rs2_addr <= rs2;
            i_rd_addr <= rd;
            #1; // Wait 1 tick for combinational forwarding to settle
        end
    endtask

    // Clear control signals
    task nop();
        begin
            @(posedge clk);
            i_op_set <= 1'b0;
            #1;
        end
    endtask

    // Automated Check Task with ANSI Colors
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

    // -------------------------------------------------------------------------
    // TEST SEQUENCE
    // -------------------------------------------------------------------------
    initial begin
        $dumpfile("scoreboard_waves.vcd");
        $dumpvars(0, tb_scoreboard);

        // Initialize
        error_count = 0;
        clk = 0;
        rst = 1;
        
        i_op_set = 0;
        i_reg_set_addr = 0;
        i_reg_state = 0;
        i_rs1_addr = 0;
        i_rs2_addr = 0;
        i_rd_addr = 0;

        // Release Reset
        #15 rst = 0;
        $display("\n--- TEST START ---\n");

        // TEST 1: Check Reset State across all ports
        eval_regs(5'd0, 5'd15, 5'd31);  
        check_val(o_rs1_state, 2'b00, "Reset: rs1 (Reg 0) is 00");
        check_val(o_rs2_state, 2'b00, "Reset: rs2 (Reg 15) is 00");
        check_val(o_rd_state,  2'b00, "Reset: rd  (Reg 31) is 00");

        // TEST 2: Basic Set and Concurrent Read
        set_reg(5'd5, 2'b01); // Mark R5 as BUSY
        set_reg(5'd6, 2'b11); // Mark R6 as MEM_BUSY
        nop(); 
        eval_regs(5'd5, 5'd6, 5'd7); // Read R5, R6, R7
        check_val(o_rs1_state, 2'b01, "Basic Read: rs1 (R5) is 01");
        check_val(o_rs2_state, 2'b11, "Basic Read: rs2 (R6) is 11");
        check_val(o_rd_state,  2'b00, "Basic Read: rd  (R7) is 00 (empty)");

        // TEST 3: Duplicate Reads
        // Scheduler might look at an instruction like ADD r5, r5, r5
        eval_regs(5'd5, 5'd5, 5'd5); 
        check_val(o_rs1_state, 2'b01, "Duplicate Read: rs1 correctly fetched R5");
        check_val(o_rs2_state, 2'b01, "Duplicate Read: rs2 correctly fetched R5");
        check_val(o_rd_state,  2'b01, "Duplicate Read: rd  correctly fetched R5");

        // TEST 4: Forwarding Bypass (Mixed hit/miss)
        // Write to R10 (2'b10). Read R10 on rs1, R5 on rs2, R10 on rd.
        // rs1 and rd should forward. rs2 should fetch from memory.
        set_and_eval(5'd10, 2'b10, 5'd10, 5'd5, 5'd10);
        check_val(o_rs1_state, 2'b10, "Forwarding: rs1 (R10) bypassed correctly");
        check_val(o_rs2_state, 2'b01, "Forwarding: rs2 (R5) fetched memory correctly");
        check_val(o_rd_state,  2'b10, "Forwarding: rd  (R10) bypassed correctly");
        
        // Ensure the write actually committed after the forwarding test
        nop();
        eval_regs(5'd10, 5'd10, 5'd10);
        check_val(o_rs1_state, 2'b10, "Commit: R10 successfully latched in memory");

        // TEST 5: Boundary Checks
        set_reg(5'd0,  2'b10);
        set_reg(5'd31, 2'b01);
        nop();
        eval_regs(5'd0, 5'd31, 5'd15);
        check_val(o_rs1_state, 2'b10, "Boundary: rs1 fetched R0 correctly");
        check_val(o_rs2_state, 2'b01, "Boundary: rs2 fetched R31 correctly");

        $display("\n--- ADVANCED TESTS ---");

        // TEST 6: Multi-Port Forwarding Collision
        // Test a scenario where rs1, rs2, and rd all need forwarding simultaneously
        // from a single write back, mimicking a scheduler evaluating a self-dependent instruction
        // while the writeback clears that very register.
        set_and_eval(5'd12, 2'b11, 5'd12, 5'd12, 5'd12);
        check_val(o_rs1_state, 2'b11, "Multi-Bypass: rs1 (R12) bypassed correctly");
        check_val(o_rs2_state, 2'b11, "Multi-Bypass: rs2 (R12) bypassed correctly");
        check_val(o_rd_state,  2'b11, "Multi-Bypass: rd  (R12) bypassed correctly");

        // TEST 7: Pipeline Back-to-Back Write & Forwarding
        // Mimic back-to-back writes finishing execution on consecutive cycles.
        set_and_eval(5'd13, 2'b01, 5'd12, 5'd13, 5'd0); // Write R13, read R12 (memory), R13 (forward), R0 (memory)
        check_val(o_rs1_state, 2'b11, "Pipelined Write 1: rs1 read old memory state");
        check_val(o_rs2_state, 2'b01, "Pipelined Write 1: rs2 correctly bypassed new state");
        
        set_and_eval(5'd14, 2'b10, 5'd13, 5'd14, 5'd12); // Write R14, read R13 (memory), R14 (forward), R12 (memory)
        check_val(o_rs1_state, 2'b01, "Pipelined Write 2: rs1 read committed R13 from prev cycle");
        check_val(o_rs2_state, 2'b10, "Pipelined Write 2: rs2 correctly bypassed new state");
        check_val(o_rd_state,  2'b11, "Pipelined Write 2: rd read committed R12 from older cycle");

        // TEST 8: Full Array Saturation
        // Fill the entire scoreboard with a specific state (2'b01)
        for (i = 0; i < DEPTH; i = i + 1) begin
            set_reg(i[ADDR_BITS-1:0], 2'b01);
        end
        nop();

        // Verify the entire array holds the saturated state.
        // Doing this in chunks of 3 via eval_regs.
        eval_regs(5'd0, 5'd1, 5'd2);
        check_val(o_rs1_state, 2'b01, "Saturation Check: R0 holds 01");
        check_val(o_rd_state,  2'b01, "Saturation Check: R2 holds 01");
        
        eval_regs(5'd15, 5'd16, 5'd17);
        check_val(o_rs2_state, 2'b01, "Saturation Check: R16 holds 01");

        eval_regs(5'd29, 5'd30, 5'd31);
        check_val(o_rs1_state, 2'b01, "Saturation Check: R29 holds 01");
        check_val(o_rd_state,  2'b01, "Saturation Check: R31 holds 01");

        // TEST 9: Rapid Clearing (Simulating Writeback Release)
        // Clear three specific registers and verify immediately.
        set_reg(5'd5, 2'b00);
        set_reg(5'd15, 2'b00);
        set_reg(5'd25, 2'b00);
        nop();
        eval_regs(5'd5, 5'd15, 5'd25);
        check_val(o_rs1_state, 2'b00, "Rapid Clear: R5 is 00");
        check_val(o_rs2_state, 2'b00, "Rapid Clear: R15 is 00");
        check_val(o_rd_state,  2'b00, "Rapid Clear: R25 is 00");
        
        // Ensure surrounding registers were not disturbed
        eval_regs(5'd4, 5'd16, 5'd24);
        check_val(o_rs1_state, 2'b01, "Rapid Clear Check: R4 untouched");
        check_val(o_rd_state,  2'b01, "Rapid Clear Check: R24 untouched");

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