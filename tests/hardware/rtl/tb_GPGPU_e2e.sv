`timescale 1ns/1ps
`include "constants.svh"

// End-to-end bench: drives the GPGPU exclusively through the AXI4-Lite top
// (gpgpu_axi), exactly as the PS does on the FPGA. Programs are loaded,
// launched and checked using only CSR/IMEM/DMEM accesses and the IRQ pin.
// The DDR model (ddr_mem) answers the AXI4 master; these programs use DMEM
// only, so every test checks that no DDR transaction is left open.
// +TEST_END is optional: without it the suite runs until the next case
// directory has no program file.
module tb_GPGPU_e2e
    import ControlPkg::*;
    import gpu_pkg::*;
#(
    parameter int unsigned NUM_CORES,
    parameter int unsigned INTERFACE_VERSION,
    parameter int unsigned CLOCK_KHZ,
    parameter int unsigned BUILD_HASH,
    parameter int unsigned BUILD_DIRTY,
    parameter int unsigned DDR_ENABLE,
    parameter int unsigned AXI_SLAVE_LATENCY_MIN,
    parameter int unsigned AXI_SLAVE_LATENCY_MAX,
    parameter int unsigned AXI_SLAVE_READY_PCT,
    parameter int unsigned AXI_SLAVE_VALID_PCT,
    parameter int unsigned AXI_SLAVE_SEED
) ();

    `include "tb_e2e_host.svh"

    reg [31:0] expected_imem [0:IMEM_ENTRIES-1];
    reg [31:0] expected_dmem [0:DMEM_ENTRIES-1];

    integer i;
    integer test_idx;
    integer test_end;
    bit has_test_end;
    integer fd;
    integer imem_errors;
    integer dmem_errors;
    integer cycle_count;
    integer program_words;
    bit found_ret;

    reg [31:0] captured_word;
    reg [1:0] resp;

    string test_root;
    string case_prefix;
    string program_name;
    string data_name;
    string dump_file;
    string prog_file;
    string data_file;

    // Run settings (plusargs)
    reg [31:0] unmapped_addr;

    // ============================================================
    // Main test loop
    // ============================================================

    initial begin
        host_init();

        `REQUIRE_PLUSARG("TEST_ROOT=%s", test_root)
        `REQUIRE_PLUSARG("TEST_IDX=%d", test_idx)
        `REQUIRE_PLUSARG("CASE_PREFIX=%s", case_prefix)
        `REQUIRE_PLUSARG("PROGRAM_FILE=%s", program_name)
        `REQUIRE_PLUSARG("DATA_FILE=%s", data_name)
        `REQUIRE_PLUSARG("UNMAPPED_ADDR=%h", unmapped_addr)

        has_test_end = $value$plusargs("TEST_END=%d", test_end) != 0;

        $display("[INFO] =================================================");
        $display("[INFO]  Starting GPGPU AXI4-Lite E2E Test Suite");
        $display("[INFO]  NUM_CORES = %0d", NUM_CORES);
        $display("[INFO]  TEST_ROOT = %0s", test_root);
        $display("[INFO] =================================================");

        // --------------------------------------------------------
        // Host interface sanity checks (once per run)
        // --------------------------------------------------------
        reset_device();
        ddr_mem.clear();
        csr_errors = 0;

        $display("\n[INFO] ---> Checking host interface...");
        expect_csr(REG_INFO, {(XLEN/2)'(INTERFACE_VERSION), (XLEN/2)'(NUM_CORES)}, "INFO");
        expect_csr(REG_INFO_MEM, {(XLEN/2)'(IMEM_ENTRIES), (XLEN/2)'(DMEM_ENTRIES)}, "INFO_MEM");
        expect_csr(REG_INFO_FEATURES, 32'(DDR_ENABLE) << FEATURE_DDR_BIT, "INFO_FEATURES");
        expect_csr(REG_INFO_CLOCK, 32'(CLOCK_KHZ), "INFO_CLOCK");
        expect_csr(REG_BUILD_ID, 32'(BUILD_HASH) | (32'(BUILD_DIRTY) << BUILD_DIRTY_BIT), "BUILD_ID");
        expect_write_resp(REG_INFO_MEM, 32'd0, AXI_SLVERR);       // identity is read-only
        expect_write_resp(REG_INFO_FEATURES, 32'd0, AXI_SLVERR);
        expect_write_resp(REG_INFO_CLOCK, 32'd0, AXI_SLVERR);
        expect_write_resp(REG_BUILD_ID, 32'd0, AXI_SLVERR);
        expect_csr(REG_STATUS, STATUS_IDLE_MASK, "STATUS");
        expect_csr(REG_IRQ_ENABLE, 32'd0, "IRQ_ENABLE");
        expect_csr(REG_IRQ_STATUS, 32'd0, "IRQ_STATUS");
        expect_write_resp(REG_INFO, 32'hFFFF_FFFF, AXI_SLVERR);   // read-only
        expect_read_resp(REG_CONTROL, AXI_SLVERR);                 // write-only
        expect_write_resp(REG_CONTROL, CONTROL_START_MASK | CONTROL_STOP_MASK, AXI_SLVERR);
        expect_read_resp(unmapped_addr, AXI_DECERR);
        expect_read_resp(IMEM_BASE + 2, AXI_DECERR);               // misaligned

        if (irq !== 1'b0) begin
            $display("  [ERROR] IRQ asserted after reset");
            csr_errors = csr_errors + 1;
        end

        // Host DMEM path (through the memory subsystem) independent of kernels.
        for (i = 0; i < DMEM_ENTRIES; i = i + DMEM_ENTRIES / 8 - 1)
            write_dmem(i, 32'hA5A5_0000 | 32'(i));
        for (i = 0; i < DMEM_ENTRIES; i = i + DMEM_ENTRIES / 8 - 1) begin
            read_dmem(i, captured_word);
            if (captured_word !== (32'hA5A5_0000 | 32'(i))) begin
                $display("  [ERROR] Host DMEM[%0d] readback: Expected %h, Found %h",
                         i, 32'hA5A5_0000 | 32'(i), captured_word);
                csr_errors = csr_errors + 1;
            end
        end

        // Fault reporting
        expect_csr(REG_FAULT_INFO, 32'd0, "FAULT_INFO after reset");
        expect_csr(REG_FAULT_LANES, 32'd0, "FAULT_LANES after reset");
        expect_write_resp(REG_FAULT_INFO, 32'd0, AXI_SLVERR);      // fault report is read-only
        expect_write_resp(REG_FAULT_LANES, 32'd0, AXI_SLVERR);
        expect_write_resp(REG_FAULT_PC, 32'd0, AXI_SLVERR);

        // All lanes misaligned; the store after the faulting load never issues.
        write_dmem(0, 32'hDEAD_BEEF);
        expect_fault("misaligned load", '{
                rv_addi(6, 0, 'h5A),
                rv_lw(5, 0, 1),
                rv_sw(6, 0, 0),
                ret_instr
            }, 32'(FAULT_MEMORY) | fault_kind(MemorySubsystemPkg::ST_MISALIGNED), all_lanes(), 32'd4);
        read_dmem(0, captured_word);
        if (captured_word !== 32'hDEAD_BEEF) begin
            $display("  [ERROR] Instruction after a fault executed: DMEM[0] = %h", captured_word);
            csr_errors = csr_errors + 1;
        end

        // Address 2 * lane: only the odd lanes are misaligned.
        expect_fault("odd lanes misaligned", '{
                rv_add(5, 31, 31),
                rv_lw(6, 5, 0),
                ret_instr
            }, 32'(FAULT_MEMORY) | fault_kind(MemorySubsystemPkg::ST_MISALIGNED),
            all_lanes() & 32'hAAAA_AAAA, 32'd4);

        // One store, two kinds: from the first 4 KiB boundary after DMEM
        // (unmapped up to FB0), even lanes are unmapped and odd misaligned.
        if (gpu_pkg::DMEM_BASE + gpu_pkg::DMEM_SIZE + 'h1000 > FB0_BASE)
            $fatal(1, "[ERROR] The fault check needs unmapped space between DMEM and FB0");
        expect_fault("unmapped and misaligned store", '{
                rv_add(5, 31, 31),
                rv_lui(6, (gpu_pkg::DMEM_BASE + gpu_pkg::DMEM_SIZE + 'hFFF) & ~32'hFFF),
                rv_add(5, 5, 6),
                rv_sw(0, 5, 0),
                ret_instr
            }, 32'(FAULT_MEMORY) | fault_kind(MemorySubsystemPkg::ST_UNMAPPED)
                            | fault_kind(MemorySubsystemPkg::ST_MISALIGNED), all_lanes(), 32'd12);

        expect_fault("store to the read-only texture region", '{
                rv_lui(5, TEX_BASE),
                rv_sw(0, 5, 0),
                ret_instr
            }, 32'(FAULT_MEMORY) | fault_kind(MemorySubsystemPkg::ST_PERMISSION), all_lanes(), 32'd4);

        // Without the DDR backend a framebuffer store is unmapped, not a hang,
        // and nothing reaches the AXI4 master.
        if (DDR_ENABLE == 0) begin
            expect_fault("framebuffer store without DDR", '{
                    rv_lui(5, FB0_BASE),
                    rv_sw(0, 5, 0),
                    ret_instr
                }, 32'(FAULT_MEMORY) | fault_kind(MemorySubsystemPkg::ST_UNMAPPED), all_lanes(), 32'd4);
            if (ddr_mem.aw_count != 0 || ddr_mem.ar_count != 0) begin
                $display("  [ERROR] DDR disabled, but %0d AW and %0d AR bursts were issued",
                         ddr_mem.aw_count, ddr_mem.ar_count);
                csr_errors = csr_errors + 1;
            end
        end

        if (csr_errors != 0)
            $fatal(1, "[ERROR] Host interface checks failed with %0d errors", csr_errors);
        $display("[INFO]  Host interface checks passed.");

        forever begin
            if (has_test_end && test_idx > test_end) begin
                $display("\n[INFO] Reached requested TEST_END=%0d. Simulation finished successfully!", test_end);
                $finish;
                // The simulator can continue this time slot after $finish.
                break;
            end

            // ----------------------------------------------------
            // Find test files
            // ----------------------------------------------------
            prog_file = $sformatf("%0s/%0s%0d/%0s", test_root, case_prefix, test_idx, program_name);
            data_file = $sformatf("%0s/%0s%0d/%0s", test_root, case_prefix, test_idx, data_name);

            fd = $fopen(prog_file, "r");
            if (fd == 0) begin
                if (test_idx == 1)
                    $fatal(1, "[ERROR] No tests were found");
                else
                    $display("\n[INFO] Simulation finished successfully!");

                $finish;
                // The simulator can continue this time slot after $finish.
                break;
            end
            $fclose(fd);

            $display("\n[INFO] ---> Starting test %0d...", test_idx);

            // ----------------------------------------------------
            // Initialize expected arrays
            // ----------------------------------------------------
            for (i = 0; i < IMEM_ENTRIES; i = i + 1)
                expected_imem[i] = NOP_INSTR;

            for (i = 0; i < DMEM_ENTRIES; i = i + 1)
                expected_dmem[i] = 32'b0;

            $readmemh(prog_file, expected_imem);
            $readmemh(data_file, expected_dmem);

            // Only load up to (and including) the kernel's RET.
            program_words = IMEM_ENTRIES;
            found_ret = 0;
            for (i = 0; i < IMEM_ENTRIES; i = i + 1) begin
                if (!found_ret && expected_imem[i] == ret_instr) begin
                    program_words = i + 1;
                    found_ret = 1;
                end
            end

            if (!found_ret)
                $display("[WARNING] No RET instruction 0x%08h found in %0s. Loading full IMEM.",
                         ret_instr, prog_file);
            else
                $display("[INFO]  Program length detected: %0d words. RET at IMEM[%0d].",
                         program_words, program_words - 1);

            // ----------------------------------------------------
            // Reset (BRAM contents survive reset)
            // ----------------------------------------------------
            reset_device();
            ddr_mem.clear();

            if (o_core_idle !== 1'b1)
                $fatal(1, "[ERROR] GPGPU did not enter idle after reset");

            // ----------------------------------------------------
            // Clear DMEM, load and verify IMEM
            // ----------------------------------------------------
            $display("[INFO]  Clearing DMEM...");
            for (i = 0; i < DMEM_ENTRIES; i = i + 1)
                write_dmem(i, 32'b0);

            $display("[INFO]  Loading IMEM...");
            for (i = 0; i < program_words; i = i + 1)
                write_imem(i, expected_imem[i]);

            $display("[INFO]  Verifying IMEM...");
            imem_errors = 0;
            for (i = 0; i < program_words; i = i + 1) begin
                read_imem(i, captured_word);
                if (captured_word !== expected_imem[i]) begin
                    $display("  [ERROR] IMEM[%0d]: Expected %h, Found %h",
                             i, expected_imem[i], captured_word);
                    imem_errors = imem_errors + 1;
                end
            end

            if (imem_errors != 0)
                $fatal(1, "[ERROR] Test %0d: IMEM verification failed with %0d errors",
                       test_idx, imem_errors);

            // ----------------------------------------------------
            // Launch and wait for the completion interrupt
            // ----------------------------------------------------
            csr_errors = 0;
            write_word(REG_IRQ_ENABLE, 32'd1);

            $display("[INFO]  Starting kernel...");
            write_word(REG_CONTROL, CONTROL_START_MASK);

            cycle_count = 0;
            while (irq !== 1'b1 && cycle_count < test_timeout_cycles) begin
                @(posedge clk_in);
                cycle_count = cycle_count + 1;
            end

            if (irq !== 1'b1)
                $fatal(1, "[ERROR] Test %0d reached timeout of %0d cycles without IRQ (idle=%b running=%b)",
                       test_idx, test_timeout_cycles, o_core_idle, o_core_running);

            $display("[INFO]  Completion IRQ after %0d cycles.", cycle_count);

            // Completion leaves the device idle and not stopped.
            expect_csr(REG_STATUS, STATUS_IDLE_MASK, "STATUS");
            expect_csr(REG_IRQ_STATUS, 32'd1, "IRQ_STATUS");

            // W1C acknowledge must drop the interrupt line.
            write_word(REG_IRQ_STATUS, 32'd1);
            @(negedge clk_in);
            if (irq !== 1'b0) begin
                $display("  [ERROR] IRQ still asserted after IRQ_STATUS W1C");
                csr_errors = csr_errors + 1;
            end
            expect_csr(REG_IRQ_STATUS, 32'd0, "IRQ_STATUS");

            if (!ddr_mem.idle()) begin
                $display("  [ERROR] A DDR transaction is still open after completion");
                csr_errors = csr_errors + 1;
            end

            // ----------------------------------------------------
            // Read back and verify DMEM
            // ----------------------------------------------------
            $display("[INFO]  Verifying DMEM...");
            dmem_errors = 0;
            for (i = 0; i < DMEM_ENTRIES; i = i + 1) begin
                read_dmem(i, captured_word);
                if (captured_word !== expected_dmem[i]) begin
                    $display("  [ERROR] DMEM[%0d]: Expected %h, Found %h",
                             i, expected_dmem[i], captured_word);
                    dmem_errors = dmem_errors + 1;
                end
            end

            // ----------------------------------------------------
            // Verdict
            // ----------------------------------------------------
            if (dmem_errors == 0 && csr_errors == 0) begin
                $display("  [SUCCESS] Test %0d passed in %0d cycles.", test_idx, cycle_count);
            end else begin
                $display("  [WARNING] Test %0d failed. DMEM errors: %0d, CSR errors: %0d",
                         test_idx, dmem_errors, csr_errors);
                $fatal(1, "[ERROR] Halting simulation due to E2E GPGPU test failure.");
            end

            test_idx = test_idx + 1;
        end
    end

    initial begin
        // Waveforms are dumped only when the runner passes +DUMP_FILE.
        if ($value$plusargs("DUMP_FILE=%s", dump_file)) begin
            $dumpfile(dump_file);
            $dumpvars(0, tb_GPGPU_e2e);
        end
    end

endmodule
