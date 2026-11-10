`timescale 1ns/1ps
`include "constants.svh"

// End-to-end bench: drives the GPGPU exclusively through the AXI4-Lite top
// (gpgpu_axi), exactly as the PS does on the FPGA. It checks the CSR map,
// error responses and fault reports, then runs the directed cases
// (run_cases, tb_e2e_host.svh): programs are loaded, launched and checked
// using only CSR/IMEM/DMEM accesses, the IRQ pin and the DDR model's backdoor.
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

    integer i;
    reg [31:0] captured_word;
    string dump_file;

    // Run settings (plusargs)
    reg [31:0] unmapped_addr;

    // ============================================================
    // Host interface checks, then the directed cases
    // ============================================================

    initial begin
        host_init();

        `REQUIRE_PLUSARG("UNMAPPED_ADDR=%h", unmapped_addr)

        $display("[INFO] =================================================");
        $display("[INFO]  Starting GPGPU AXI4-Lite E2E Test Suite");
        $display("[INFO]  NUM_CORES = %0d", NUM_CORES);
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

        // Performance counter block: read-only, zero before any run, and a
        // slot with no counter (or a misaligned word) is not mapped
        expect_csr(PERF_GLOBAL_BASE + PERF_COUNTER_BYTES * PerfPkg::PERF_KERNEL_CYCLES, 32'd0, "PERF_KERNEL_CYCLES");
        expect_csr(PERF_GLOBAL_BASE + PERF_COUNTER_BYTES * PerfPkg::PERF_KERNEL_CYCLES + PERF_HI_OFFSET, 32'd0,
                   "PERF_KERNEL_CYCLES high word");
        expect_write_resp(PERF_GLOBAL_BASE, 32'd0, AXI_SLVERR);
        expect_write_resp(PERF_WARP_BASE, 32'd0, AXI_SLVERR);
        expect_read_resp(PERF_GLOBAL_BASE + PERF_COUNTER_BYTES * PerfPkg::PERF_GLOBAL_COUNT, AXI_DECERR);
        expect_read_resp(PERF_WARP_BASE + PERF_COUNTER_BYTES * PerfPkg::PERF_WARP_LEAF_COUNT, AXI_DECERR);
        expect_read_resp(PERF_WARP_BASE + PERF_WARP_STRIDE * warp_pkg::WARPS_PER_SM, AXI_DECERR);
        expect_read_resp(PERF_GLOBAL_BASE + 2, AXI_DECERR);

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

        run_cases();
    end

    initial begin
        // Waveforms are dumped only when the runner passes +DUMP_FILE.
        if ($value$plusargs("DUMP_FILE=%s", dump_file)) begin
            $dumpfile(dump_file);
            $dumpvars(0, tb_GPGPU_e2e);
        end
    end

endmodule
