`timescale 1ns/1ps
`include "constants.svh"

// Every run setting is a required plusarg (supplied by the runner from the
// config file); a missing one is fatal. +TEST_END is optional: without it the
// suite runs until the next case directory has no program file.
`define REQUIRE_PLUSARG(fmt, var) \
    if (!$value$plusargs(fmt, var)) $fatal(1, "[ERROR] Missing required plusarg +%0s", fmt);

// End-to-end bench: drives the GPGPU exclusively through the AXI4-Lite top
// (gpgpu_axi), exactly as the PS does on the FPGA. Programs are loaded,
// launched and checked using only CSR/IMEM/DMEM accesses and the IRQ pin.
module tb_GPGPU_e2e
    import ControlPkg::*;
    import gpu_pkg::*;
#(
    parameter int unsigned NUM_CORES
) ();

    // AXI response codes
    localparam logic [1:0] AXI_OKAY = 2'b00;
    localparam logic [1:0] AXI_SLVERR = 2'b10;
    localparam logic [1:0] AXI_DECERR = 2'b11;

    reg clk_in;
    reg aresetn;

    // AXI4-Lite master signals
    reg [31:0] awaddr;
    reg awvalid;
    wire awready;
    reg [31:0] wdata;
    reg [3:0] wstrb;
    reg wvalid;
    wire wready;
    wire [1:0] bresp;
    wire bvalid;
    reg bready;
    reg [31:0] araddr;
    reg arvalid;
    wire arready;
    wire [31:0] rdata;
    wire [1:0] rresp;
    wire rvalid;
    reg rready;

    wire irq;
    wire o_core_idle;
    wire o_core_running;

    reg [31:0] expected_imem [0:IMEM_ENTRIES-1];
    reg [31:0] expected_dmem [0:DMEM_ENTRIES-1];

    integer i;
    integer test_idx;
    integer test_end;
    bit has_test_end;
    integer fd;
    integer imem_errors;
    integer dmem_errors;
    integer csr_errors;
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
    real clock_period_ns;
    integer reset_cycles;
    integer test_timeout_cycles;
    integer axi_timeout_cycles;
    reg [31:0] ret_instr;
    reg [31:0] unmapped_addr;
    reg [31:0] info_version;
    bit settings_ready = 1'b0;

    // ============================================================
    // DUT
    // ============================================================

    gpgpu_axi #(
        .SP_PER_SM(NUM_CORES)
    ) UUT (
        .irq(irq),
        .o_core_idle(o_core_idle),
        .o_core_running(o_core_running),

        .s00_axi_aclk(clk_in),
        .s00_axi_aresetn(aresetn),
        .s00_axi_awaddr(awaddr),
        .s00_axi_awprot(3'b000),
        .s00_axi_awvalid(awvalid),
        .s00_axi_awready(awready),
        .s00_axi_wdata(wdata),
        .s00_axi_wstrb(wstrb),
        .s00_axi_wvalid(wvalid),
        .s00_axi_wready(wready),
        .s00_axi_bresp(bresp),
        .s00_axi_bvalid(bvalid),
        .s00_axi_bready(bready),
        .s00_axi_araddr(araddr),
        .s00_axi_arprot(3'b000),
        .s00_axi_arvalid(arvalid),
        .s00_axi_arready(arready),
        .s00_axi_rdata(rdata),
        .s00_axi_rresp(rresp),
        .s00_axi_rvalid(rvalid),
        .s00_axi_rready(rready)
    );

    initial begin
        wait (settings_ready);
        forever #(clock_period_ns / 2.0) clk_in = ~clk_in;
    end

    // ============================================================
    // AXI4-Lite master
    // ============================================================
    // Inputs are driven on the falling edge. READY/VALID sampled at the
    // falling edge are stable up to the next rising edge, where the
    // handshake completes.

    task automatic axi_write(
        input [31:0] addr,
        input [31:0] data,
        input [3:0] strb,
        output [1:0] response
    );
        integer timeout;
        reg aw_done, w_done;
        begin
            @(negedge clk_in);
            awaddr = addr; awvalid = 1'b1;
            wdata = data; wstrb = strb; wvalid = 1'b1;
            aw_done = 1'b0; w_done = 1'b0;
            timeout = 0;

            // Address and data channels complete independently.
            while (!(aw_done && w_done)) begin
                if (timeout >= axi_timeout_cycles)
                    $fatal(1, "[ERROR] AXI write timeout (AW/W) addr=%h", addr);
                if (awvalid && awready) aw_done = 1'b1;
                if (wvalid && wready) w_done = 1'b1;
                @(negedge clk_in);
                if (aw_done) awvalid = 1'b0;
                if (w_done) wvalid = 1'b0;
                timeout = timeout + 1;
            end

            bready = 1'b1;
            timeout = 0;
            while (!bvalid) begin
                if (timeout >= axi_timeout_cycles)
                    $fatal(1, "[ERROR] AXI write timeout (B) addr=%h", addr);
                @(negedge clk_in);
                timeout = timeout + 1;
            end
            response = bresp;
            @(negedge clk_in);
            bready = 1'b0;
        end
    endtask

    task automatic axi_read(
        input [31:0] addr,
        output [31:0] data,
        output [1:0] response
    );
        integer timeout;
        begin
            @(negedge clk_in);
            araddr = addr; arvalid = 1'b1;
            timeout = 0;

            while (!arready) begin
                if (timeout >= axi_timeout_cycles)
                    $fatal(1, "[ERROR] AXI read timeout (AR) addr=%h", addr);
                @(negedge clk_in);
                timeout = timeout + 1;
            end
            @(negedge clk_in);
            arvalid = 1'b0;

            rready = 1'b1;
            timeout = 0;
            while (!rvalid) begin
                if (timeout >= axi_timeout_cycles)
                    $fatal(1, "[ERROR] AXI read timeout (R) addr=%h", addr);
                @(negedge clk_in);
                timeout = timeout + 1;
            end
            data = rdata;
            response = rresp;
            @(negedge clk_in);
            rready = 1'b0;
        end
    endtask

    // ============================================================
    // Device access helpers (expect OKAY)
    // ============================================================

    task automatic write_word(input [31:0] addr, input [31:0] data);
        reg [1:0] response;
        begin
            axi_write(addr, data, 4'b1111, response);
            if (response !== AXI_OKAY)
                $fatal(1, "[ERROR] Write addr=%h data=%h failed with resp=%b", addr, data, response);
        end
    endtask

    task automatic read_word(input [31:0] addr, output [31:0] data);
        reg [1:0] response;
        begin
            axi_read(addr, data, response);
            if (response !== AXI_OKAY)
                $fatal(1, "[ERROR] Read addr=%h failed with resp=%b", addr, response);
        end
    endtask

    task automatic write_imem(input integer index, input [31:0] data);
        write_word(IMEM_BASE + 32'(index) * 4, data);
    endtask

    task automatic read_imem(input integer index, output [31:0] data);
        read_word(IMEM_BASE + 32'(index) * 4, data);
    endtask

    task automatic write_dmem(input integer index, input [31:0] data);
        write_word(ControlPkg::DMEM_BASE + 32'(index) * 4, data);
    endtask

    task automatic read_dmem(input integer index, output [31:0] data);
        read_word(ControlPkg::DMEM_BASE + 32'(index) * 4, data);
    endtask

    // Read a CSR and compare against an expected value; counts mismatches.
    task automatic expect_csr(input [31:0] addr, input [31:0] expected, input string name);
        reg [31:0] data;
        begin
            read_word(addr, data);
            if (data !== expected) begin
                $display("  [ERROR] %0s (0x%0h): Expected %h, Found %h", name, addr, expected, data);
                csr_errors = csr_errors + 1;
            end
        end
    endtask

    task automatic expect_write_resp(input [31:0] addr, input [31:0] data, input [1:0] expected);
        reg [1:0] response;
        begin
            axi_write(addr, data, 4'b1111, response);
            if (response !== expected) begin
                $display("  [ERROR] Write addr=%h: Expected resp %b, Found %b", addr, expected, response);
                csr_errors = csr_errors + 1;
            end
        end
    endtask

    task automatic expect_read_resp(input [31:0] addr, input [1:0] expected);
        reg [31:0] data;
        reg [1:0] response;
        begin
            axi_read(addr, data, response);
            if (response !== expected) begin
                $display("  [ERROR] Read addr=%h: Expected resp %b, Found %b", addr, expected, response);
                csr_errors = csr_errors + 1;
            end
        end
    endtask

    task automatic reset_device;
        begin
            aresetn = 1'b0;
            repeat (reset_cycles) @(posedge clk_in);
            @(negedge clk_in);
            aresetn = 1'b1;
            repeat (5) @(posedge clk_in);
        end
    endtask

    // ============================================================
    // Main test loop
    // ============================================================

    initial begin
        clk_in = 1'b0;
        aresetn = 1'b0;

        awaddr = '0; awvalid = 1'b0;
        wdata = '0; wstrb = '0; wvalid = 1'b0;
        bready = 1'b0;
        araddr = '0; arvalid = 1'b0;
        rready = 1'b0;

        `REQUIRE_PLUSARG("TEST_ROOT=%s", test_root)
        `REQUIRE_PLUSARG("TEST_IDX=%d", test_idx)
        `REQUIRE_PLUSARG("CASE_PREFIX=%s", case_prefix)
        `REQUIRE_PLUSARG("PROGRAM_FILE=%s", program_name)
        `REQUIRE_PLUSARG("DATA_FILE=%s", data_name)
        `REQUIRE_PLUSARG("CLOCK_PERIOD_NS=%f", clock_period_ns)
        `REQUIRE_PLUSARG("RESET_CYCLES=%d", reset_cycles)
        `REQUIRE_PLUSARG("TEST_TIMEOUT_CYCLES=%d", test_timeout_cycles)
        `REQUIRE_PLUSARG("AXI_TIMEOUT_CYCLES=%d", axi_timeout_cycles)
        `REQUIRE_PLUSARG("RET_INSTR=%h", ret_instr)
        `REQUIRE_PLUSARG("UNMAPPED_ADDR=%h", unmapped_addr)
        `REQUIRE_PLUSARG("INFO_VERSION=%d", info_version)
        settings_ready = 1'b1;

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
        csr_errors = 0;

        $display("\n[INFO] ---> Checking host interface...");
        expect_csr(REG_INFO, {info_version[XLEN/2-1:0], (XLEN/2)'(NUM_CORES)}, "INFO");
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
