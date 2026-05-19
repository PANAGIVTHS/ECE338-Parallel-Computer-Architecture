`timescale 1ns/1ps
`include "constants.vh"

`define CLOCK_PERIOD 10
`define TEST_TIMEOUT_CYCLES 1500
`define HOST_TIMEOUT_CYCLES 10000

module tb_GPGPU_e2e ();

    parameter NUM_CORES = 33;

    // Host command encodings
    localparam CMD_IMEM_WRITE = 3'd0;
    localparam CMD_DMEM_WRITE = 3'd1;
    localparam CMD_WRITE_DONE = 3'd2;
    localparam CMD_DMEM_READ  = 3'd3;
    localparam CMD_IMEM_READ  = 3'd4;
    localparam CMD_REG_READ   = 3'd5;
    localparam CMD_READ_DONE  = 3'd6;
    localparam RET_INSTR = 32'h00008067;

    reg clk_in;
    reg rst;

    wire o_loading;
    wire o_running;
    wire o_dumping;

    reg [2:0]  host_command;
    reg        host_command_valid;
    reg [31:0] host_address;
    reg [31:0] host_wdata;

    wire [31:0] host_rdata;
    wire host_busy;
    wire host_done;

    reg [31:0] expected_imem [0:`IMEM_ENTRIES-1];
    reg [31:0] expected_dmem [0:`DMEM_ENTRIES-1];

    integer i;
    integer test_idx;
    integer fd;
    integer imem_errors;
    integer dmem_errors;
    integer cycle_count;
    integer timeout_count;
    integer program_words;
    integer found_ret;

    reg [31:0] captured_word;

    reg [8*255:0] test_root;
    reg [8*255:0] prog_file;
    reg [8*255:0] data_file;

    // ============================================================
    // DUT
    // ============================================================

    GPGPU #(
        .SP_PER_SM(NUM_CORES),
        .MEMORY_INIT("../src/memory/empty.mem")
    ) UUT (
        .clk_in(clk_in),
        .rst(rst),

        .o_loading(o_loading),
        .o_running(o_running),
        .o_dumping(o_dumping),

        .i_host_command(host_command),
        .i_host_command_valid(host_command_valid),
        .i_host_address(host_address),
        .i_host_wdata(host_wdata),

        .o_host_rdata(host_rdata),
        .o_host_busy(host_busy),
        .o_host_done(host_done)
    );

    always #(`CLOCK_PERIOD / 2) clk_in = ~clk_in;

    // ============================================================
    // Host command helpers
    // ============================================================

    task wait_not_busy;
        begin
            timeout_count = 0;

            while (host_busy && timeout_count < `HOST_TIMEOUT_CYCLES) begin
                @(posedge clk_in);
                timeout_count = timeout_count + 1;
            end

            if (timeout_count >= `HOST_TIMEOUT_CYCLES) begin
                $fatal(1, "[HOST ERROR] Timeout waiting for host_busy=0");
            end
        end
    endtask

    task wait_done_high;
        begin
            timeout_count = 0;

            while (!host_done && timeout_count < `HOST_TIMEOUT_CYCLES) begin
                @(posedge clk_in);
                timeout_count = timeout_count + 1;
            end

            if (timeout_count >= `HOST_TIMEOUT_CYCLES) begin
                $fatal(1,
                    "[HOST ERROR] Timeout waiting for host_done=1. cmd=%0d addr=%0d",
                    host_command,
                    host_address
                );
            end
        end
    endtask

    task wait_done_low;
        begin
            timeout_count = 0;

            while (host_done && timeout_count < `HOST_TIMEOUT_CYCLES) begin
                @(posedge clk_in);
                timeout_count = timeout_count + 1;
            end

            if (timeout_count >= `HOST_TIMEOUT_CYCLES) begin
                $fatal(1, "[HOST ERROR] Timeout waiting for host_done=0");
            end
        end
    endtask

    task begin_command(
        input [2:0]  cmd,
        input [31:0] addr,
        input [31:0] wdata
    );
        begin
            wait_not_busy();

            @(posedge clk_in);
            host_command       <= cmd;
            host_address       <= addr;
            host_wdata         <= wdata;
            host_command_valid <= 1'b1;

            wait_done_high();
        end
    endtask

    task end_command(
        input [2:0] cmd
    );
        begin
            @(posedge clk_in);
            host_command       <= cmd;
            host_command_valid <= 1'b0;

            wait_done_low();

            @(posedge clk_in);
        end
    endtask

    task send_command(
        input [2:0]  cmd,
        input [31:0] addr,
        input [31:0] wdata
    );
        begin
            begin_command(cmd, addr, wdata);
            end_command(cmd);
        end
    endtask

    task write_imem(
        input [31:0] addr,
        input [31:0] data
    );
        begin
            send_command(CMD_IMEM_WRITE, addr, data);
        end
    endtask

    task write_dmem(
        input [31:0] addr,
        input [31:0] data
    );
        begin
            send_command(CMD_DMEM_WRITE, addr, data);
        end
    endtask

    task read_imem(
        input [31:0] addr,
        output [31:0] data
    );
        begin
            begin_command(CMD_IMEM_READ, addr, 32'b0);
            data = host_rdata;
            end_command(CMD_IMEM_READ);
        end
    endtask

    task read_dmem(
        input [31:0] addr,
        output [31:0] data
    );
        begin
            begin_command(CMD_DMEM_READ, addr, 32'b0);
            data = host_rdata;
            end_command(CMD_DMEM_READ);
        end
    endtask

    task start_core;
        begin
            send_command(CMD_WRITE_DONE, 32'b0, 32'b0);
        end
    endtask

    task finish_dumping;
        begin
            send_command(CMD_READ_DONE, 32'b0, 32'b0);
        end
    endtask

    // ============================================================
    // Main test loop
    // ============================================================

    initial begin
        clk_in = 1'b0;
        rst = 1'b0;

        host_command       = 3'b0;
        host_command_valid = 1'b0;
        host_address       = 32'b0;
        host_wdata         = 32'b0;

        if (!$value$plusargs("TEST_ROOT=%s", test_root)) begin
            test_root = "tests";
        end

        $display("[INFO] TEST_ROOT = %0s", test_root);

        if (!$value$plusargs("TEST_IDX=%d", test_idx)) begin
            test_idx = 1;
        end

        $display("[INFO] =================================================");
        $display("[INFO]  Starting GPGPU Public-Interface E2E Test Suite");
        $display("[INFO]  NUM_CORES = %0d", NUM_CORES);
        $display("[INFO] =================================================");

        forever begin
            // ----------------------------------------------------
            // Find test files
            // ----------------------------------------------------
            $sformat(prog_file, "%0s/test%0d/program.mem", test_root, test_idx);
            $sformat(data_file, "%0s/test%0d/data.mem", test_root, test_idx);

            fd = $fopen(prog_file, "r");
            if (fd == 0) begin
                if (test_idx == 1) begin
                    $display("[ERROR] No tests were found");
                end else begin
                    $display("\n[INFO] Simulation finished successfully!");
                end

                #(`CLOCK_PERIOD * 20);
                $finish;
            end
            $fclose(fd);

            $display("\n[INFO] ---> Starting test %0d...", test_idx);

            // ----------------------------------------------------
            // Initialize expected arrays
            // ----------------------------------------------------
            for (i = 0; i < `IMEM_ENTRIES; i = i + 1)
                expected_imem[i] = `NOP_INSTR;

            for (i = 0; i < `DMEM_ENTRIES; i = i + 1)
                expected_dmem[i] = 32'b0;

            $readmemh(prog_file, expected_imem);
            $readmemh(data_file, expected_dmem);
            program_words = `IMEM_ENTRIES;
            found_ret = 0;

            for (i = 0; i < `IMEM_ENTRIES; i = i + 1) begin
                if (!found_ret && expected_imem[i] == RET_INSTR) begin
                    program_words = i + 1;
                    found_ret = 1;
                end
            end

            if (!found_ret) begin
                $display("[WARNING] No RET instruction 0x%08h found in %0s. Loading full IMEM.",
                        RET_INSTR, prog_file);
            end else begin
                $display("[INFO]  Program length detected: %0d words. RET at IMEM[%0d].",
                        program_words, program_words - 1);
            end

            // ----------------------------------------------------
            // Reset
            // ----------------------------------------------------
            rst = 1'b0;
            repeat (20) @(posedge clk_in);

            rst = 1'b1;
            repeat (20) @(posedge clk_in);

            if (o_loading !== 1'b1) begin
                $display("  [WARNING] GPGPU did not enter loading state after reset.");
            end

            // ----------------------------------------------------
            // Clear DMEM through host interface
            // ----------------------------------------------------
            $display("[INFO]  Clearing DMEM through host command interface...");

            for (i = 0; i < `DMEM_ENTRIES; i = i + 1) begin
                write_dmem(i, 32'b0);

                if (i > 0 && i % 256 == 0)
                    $display("    ...cleared %0d DMEM words", i);
            end

            // ----------------------------------------------------
            // Load IMEM through host interface
            // ----------------------------------------------------
            $display("[INFO]  Loading IMEM through host command interface...");

            for (i = 0; i < program_words; i = i + 1) begin
                write_imem(i, expected_imem[i]);

                if (i > 0 && i % 256 == 0)
                    $display("[INFO]    ...loaded %0d IMEM words", i);
            end

            $display("[INFO]  Loaded %0d IMEM words.", program_words);

            // ----------------------------------------------------
            // Read back IMEM and verify
            // ----------------------------------------------------
            $display("[INFO]  Verifying IMEM through host command interface...");

            imem_errors = 0;

            for (i = 0; i < program_words; i = i + 1) begin
                read_imem(i, captured_word);

                if (captured_word !== expected_imem[i]) begin
                    $display("  [ERROR] IMEM[%0d]: Expected %h, Found %h",
                            i, expected_imem[i], captured_word);
                    imem_errors = imem_errors + 1;
                end
            end

            if (imem_errors == 0) begin
                $display("[INFO]  IMEM verification passed.");
            end

            // ----------------------------------------------------
            // Start core
            // ----------------------------------------------------
            $display("[INFO]  Starting core...");
            start_core();

            // ----------------------------------------------------
            // Wait for dumping state
            // ----------------------------------------------------
            cycle_count = 0;

            while (o_dumping !== 1'b1 && cycle_count < `TEST_TIMEOUT_CYCLES) begin
                @(posedge clk_in);
                cycle_count = cycle_count + 1;
            end

            if (cycle_count >= `TEST_TIMEOUT_CYCLES) begin
                $display("  [WARNING] Test %0d reached timeout of %0d cycles!",
                         test_idx, `TEST_TIMEOUT_CYCLES);
            end else begin
                $display("[INFO]  Core reached dumping state in %0d cycles.", cycle_count);
            end

            repeat (10) @(posedge clk_in);

            // ----------------------------------------------------
            // Read back and verify DMEM
            // ----------------------------------------------------
            $display("[INFO]  Verifying DMEM through host command interface...");

            dmem_errors = 0;

            for (i = 0; i < `DMEM_ENTRIES; i = i + 1) begin
                read_dmem(i, captured_word);

                if (captured_word !== expected_dmem[i]) begin
                    $display("  [ERROR] DMEM[%0d]: Expected %h, Found %h",
                             i, expected_dmem[i], captured_word);
                    dmem_errors = dmem_errors + 1;
                end
            end

            // ----------------------------------------------------
            // Return controller to loading state
            // ----------------------------------------------------
            finish_dumping();

            // ----------------------------------------------------
            // Verdict
            // ----------------------------------------------------
            if (imem_errors == 0 && dmem_errors == 0) begin
                $display("  [SUCCESS] Test %0d passed. IMEM and DMEM matched. Finished in %0d cycles.",
                         test_idx, cycle_count);
            end else begin
                $display("  [INFO] Test %0d failed. IMEM errors: %0d, DMEM errors: %0d",
                         test_idx, imem_errors, dmem_errors);

                $fatal(1, "[ERROR] Halting simulation due to public-interface GPGPU test failure.");
            end

            test_idx = test_idx + 1;
        end
    end

    initial begin
        $dumpfile("dumpfile.vcd");
        $dumpvars(0, tb_GPGPU_e2e);
    end

endmodule