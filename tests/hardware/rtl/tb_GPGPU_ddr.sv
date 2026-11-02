`timescale 1ns/1ps
`include "constants.svh"

// DDR end-to-end bench: the GPGPU through its AXI4-Lite top (as in
// tb_GPGPU_e2e) with DDR_ENABLE = 1 and the AXI4SlaveMemory model behind the
// AXI4 master. Kernels store to the framebuffers; the bench checks memory
// through the model's backdoor, the burst count, the handshake idle state
// and the fault report for injected AXI errors.
//
// Stores only: the DDR read ring does not exist yet, so a DDR load would
// never be accepted.
module tb_GPGPU_ddr
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

    if (DDR_ENABLE == 0) begin : g_ddr_check
        $fatal(1, "tb_GPGPU_ddr needs DDR_ENABLE = 1");
    end

    localparam int unsigned GROUP_BYTES = DDRBackendPkg::GROUP_BYTES;
    localparam int unsigned LOOP_ITERATIONS = 64;

    // Bytes of one store per lane
    localparam int unsigned LANE_BYTES = NUM_CORES * 4;

    integer errors;
    string dump_file;

    // ============================================================
    // Checks
    // ============================================================

    function automatic void expect_mem(input string name, input logic [31:0] addr, input logic [31:0] want);
        logic [31:0] found;
        found = ddr_mem.read_word(addr);
        if (found !== want) begin
            $display("  [ERROR] %0s: DDR[%h] = %h, expected %h", name, addr, found, want);
            errors = errors + 1;
        end
    endfunction

    function automatic void expect_bursts(input string name, input int unsigned want);
        if (ddr_mem.aw_count != want) begin
            $display("  [ERROR] %0s: %0d write bursts, expected %0d", name, ddr_mem.aw_count, want);
            errors = errors + 1;
        end
    endfunction

    // A kernel that completed without a fault leaves the device idle and the
    // AXI4 master with nothing open.
    task automatic expect_clean(input string name);
        expect_csr(REG_STATUS, STATUS_IDLE_MASK, {name, ": STATUS"});
        if (!ddr_mem.idle()) begin
            $display("  [ERROR] %0s: a DDR transaction is still open", name);
            errors = errors + 1;
        end
    endtask

    // ceil(bytes / GROUP_BYTES): bursts for a contiguous, group-aligned span
    function automatic int unsigned groups(input int unsigned bytes);
        return (bytes + GROUP_BYTES - 1) / GROUP_BYTES;
    endfunction

    // ============================================================
    // Tests
    // ============================================================

    initial begin
        logic [31:0] base;
        logic [31:0] lanes;
        int unsigned error_lane;

        host_init();
        errors = 0;
        csr_errors = 0;

        $display("[INFO] =================================================");
        $display("[INFO]  Starting GPGPU DDR E2E Test Suite");
        $display("[INFO]  NUM_CORES = %0d", NUM_CORES);
        $display("[INFO] =================================================");

        reset_device();
        ddr_mem.clear();
        expect_csr(REG_INFO_FEATURES, FEATURE_DDR_MASK, "INFO_FEATURES");

        // --------------------------------------------------------
        // Consecutive words: one group per GROUP_BYTES
        // --------------------------------------------------------
        $display("\n[INFO] ---> Consecutive words");
        ddr_mem.clear();
        base = FB0_BASE;
        run_kernel('{
            rv_lui(5, base),
            rv_slli(6, 31, 2),
            rv_add(5, 5, 6),
            rv_addi(7, 31, 1),
            rv_sw(7, 5, 0),
            ret_instr
        });
        expect_clean("consecutive");
        for (int lane = 0; lane < NUM_CORES; lane++)
            expect_mem("consecutive", base + 4 * lane, 32'(lane + 1));
        expect_bursts("consecutive", groups(LANE_BYTES));

        // --------------------------------------------------------
        // One group per lane: more groups than write slots
        // --------------------------------------------------------
        $display("\n[INFO] ---> One group per lane");
        ddr_mem.clear();
        base = FB0_BASE + 'h1000;
        run_kernel('{
            rv_lui(5, base),
            rv_slli(6, 31, $clog2(GROUP_BYTES)),
            rv_add(5, 5, 6),
            rv_addi(7, 31, 'h100),
            rv_sw(7, 5, 0),
            ret_instr
        });
        expect_clean("group per lane");
        for (int lane = 0; lane < NUM_CORES; lane++)
            expect_mem("group per lane", base + GROUP_BYTES * lane, 32'(lane + 'h100));
        expect_bursts("group per lane", NUM_CORES);

        // --------------------------------------------------------
        // Every other word: gaps in a burst carry WSTRB = 0
        // --------------------------------------------------------
        $display("\n[INFO] ---> Every other word");
        ddr_mem.clear();
        base = FB0_BASE + 'h2000;
        for (int lane = 0; lane < NUM_CORES; lane++)
            ddr_mem.write_word(base + 8 * lane + 4, 32'hCAFE_0000 | 32'(lane));
        run_kernel('{
            rv_lui(5, base),
            rv_slli(6, 31, 3),
            rv_add(5, 5, 6),
            rv_addi(7, 31, 'h200),
            rv_sw(7, 5, 0),
            ret_instr
        });
        expect_clean("every other word");
        for (int lane = 0; lane < NUM_CORES; lane++) begin
            expect_mem("every other word", base + 8 * lane, 32'(lane + 'h200));
            expect_mem("every other word (gap)", base + 8 * lane + 4, 32'hCAFE_0000 | 32'(lane));
        end
        expect_bursts("every other word", groups(2 * LANE_BYTES));

        // --------------------------------------------------------
        // Same word from every lane: one of the stores wins whole
        // --------------------------------------------------------
        $display("\n[INFO] ---> Same word from every lane");
        ddr_mem.clear();
        base = FB0_BASE + 'h3000;
        run_kernel('{
            rv_lui(5, base),
            rv_addi(7, 31, 1),
            rv_sw(7, 5, 0),
            ret_instr
        });
        expect_clean("same word");
        begin
            logic [31:0] found;
            found = ddr_mem.read_word(base);
            if (found < 1 || found > NUM_CORES) begin
                $display("  [ERROR] same word: DDR[%h] = %h is no lane's store", base, found);
                errors = errors + 1;
            end
        end
        expect_bursts("same word", 1);

        // --------------------------------------------------------
        // Sustained stores: a loop of LOOP_ITERATIONS rows into FB1
        // --------------------------------------------------------
        $display("\n[INFO] ---> Store loop");
        ddr_mem.clear();
        base = FB1_BASE;
        run_kernel('{
            rv_lui(5, base),
            rv_slli(6, 31, 2),
            rv_add(5, 5, 6),                // x5: this lane's word in row 0
            rv_addi(8, 0, LOOP_ITERATIONS), // x8: rows left
            rv_addi(9, 0, LANE_BYTES),      // x9: row stride
            rv_slli(7, 8, 8),               // loop: value = rows left << 8 | lane
            rv_add(7, 7, 31),
            rv_sw(7, 5, 0),
            rv_add(5, 5, 9),
            rv_addi(8, 8, -1),
            rv_bne(8, 0, -20),
            ret_instr
        });
        expect_clean("store loop");
        for (int row = 0; row < LOOP_ITERATIONS; row++)
            for (int lane = 0; lane < NUM_CORES; lane++)
                expect_mem("store loop", base + LANE_BYTES * row + 4 * lane,
                           32'(((LOOP_ITERATIONS - row) << 8) | lane));
        expect_bursts("store loop", LOOP_ITERATIONS * groups(LANE_BYTES));

        // --------------------------------------------------------
        // SLVERR on a burst reaches every member and leaves memory unchanged
        // --------------------------------------------------------
        ddr_mem.clear();
        base = FB0_BASE + 'h4000;
        ddr_mem.set_error(base, AXI4FullPkg::AXI_RESP_SLVERR);
        // Lanes in the first group fault; with more lanes than one group
        // holds, the rest complete.
        lanes = all_lanes() & 32'((64'd1 << (GROUP_BYTES / 4)) - 1);
        expect_fault("SLVERR on a burst", '{
                rv_lui(5, base),
                rv_slli(6, 31, 2),
                rv_add(5, 5, 6),
                rv_sw(31, 5, 0),
                ret_instr
            }, 32'(FAULT_MEMORY) | fault_kind(MemorySubsystemPkg::ST_SLVERR), lanes, 32'd12);
        expect_mem("SLVERR on a burst", base, 32'd0);
        ddr_mem.set_error(base, AXI4FullPkg::AXI_RESP_OKAY);

        // --------------------------------------------------------
        // DECERR on one of several bursts: only that burst's lanes fault
        // --------------------------------------------------------
        ddr_mem.clear();
        base = FB0_BASE + 'h5000;
        error_lane = NUM_CORES - 1;
        ddr_mem.set_error(base + GROUP_BYTES * error_lane, AXI4FullPkg::AXI_RESP_DECERR);
        expect_fault("DECERR on one burst", '{
                rv_lui(5, base),
                rv_slli(6, 31, $clog2(GROUP_BYTES)),
                rv_add(5, 5, 6),
                rv_sw(31, 5, 0),
                ret_instr
            }, 32'(FAULT_MEMORY) | fault_kind(MemorySubsystemPkg::ST_DECERR), 32'd1 << error_lane, 32'd12);
        for (int lane = 0; lane < NUM_CORES - 1; lane++)
            expect_mem("DECERR on one burst", base + GROUP_BYTES * lane, 32'(lane));
        ddr_mem.set_error(base + GROUP_BYTES * error_lane, AXI4FullPkg::AXI_RESP_OKAY);

        if (!ddr_mem.idle()) begin
            $display("  [ERROR] A DDR transaction is still open at the end");
            errors = errors + 1;
        end

        if (errors != 0 || csr_errors != 0)
            $fatal(1, "[ERROR] DDR checks failed: %0d memory errors, %0d CSR errors", errors, csr_errors);
        $display("\n[INFO] Simulation finished successfully!");
        $finish;
    end

    initial begin
        // Waveforms are dumped only when the runner passes +DUMP_FILE.
        if ($value$plusargs("DUMP_FILE=%s", dump_file)) begin
            $dumpfile(dump_file);
            $dumpvars(0, tb_GPGPU_ddr);
        end
    end

endmodule
