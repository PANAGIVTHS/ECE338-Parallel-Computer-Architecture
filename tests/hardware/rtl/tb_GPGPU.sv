`timescale 1ns/1ps
`include "constants.svh"

`define CLOCK_PERIOD 10
`define TEST_TIMEOUT_CYCLES 1500

module tb_GPGPU_smx_only 
    import ControlPkg::*;
    import gpu_pkg::*;
#(
    parameter NUM_CORES = 32,
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

    reg clk_in, rst;

    wire o_idle;
    wire o_running;

    reg [31:0] expected_data [0:DMEM_ENTRIES-1];
    reg [31:0] expected_regfile [0:NUM_CORES-1][0:31];
    reg [31:0] temp_regfile [0:31];

    integer i, c;
    integer test_idx;
    integer test_end;
    integer has_test_end;
    integer fd;
    integer data_errors, reg_errors, perf_errors;
    integer cycle_count;
    integer fd_trace;

    reg [8*255:0] prog_file;
    reg [8*255:0] data_file;
    reg [8*255:0] reg_file;
    reg [8*255:0] trace_file;
    string dump_file;
    string ddr_file, ddr_seed_file;
    bit has_ddr;
    int unsigned ddr_errors;

    AXI4FullInterface ddr_axi ();

    GPGPU #(.SP_PER_SM(NUM_CORES), .MEMORY_INIT(""), .INTERFACE_VERSION(INTERFACE_VERSION),
           .CLOCK_KHZ(CLOCK_KHZ), .BUILD_HASH(BUILD_HASH), .BUILD_DIRTY(BUILD_DIRTY != 0),
           .DDR_ENABLE(DDR_ENABLE != 0)) UUT (
        .clk(clk_in), .rst_n(rst),
        .o_core_idle(), .o_core_running(),
        .i_req_valid(1'b0), .o_req_ready(), .i_req_write(1'b0),
        .i_req_addr(32'b0), .i_req_wdata(32'b0), .i_req_wstrb(4'b0),
        .o_rsp_valid(), .i_rsp_ready(1'b1), .o_rsp_rdata(),
        .o_rsp_status(), .o_irq(),
        `AXI4_SLAVE_CONNECT(m_axi, ddr_axi)
    );

    // DDR model on the AXI4 master; these programs use DMEM only.
    AXI4SlaveMemory #(
        .LATENCY_MIN(AXI_SLAVE_LATENCY_MIN), .LATENCY_MAX(AXI_SLAVE_LATENCY_MAX),
        .READY_PCT(AXI_SLAVE_READY_PCT), .VALID_PCT(AXI_SLAVE_VALID_PCT), .SEED(AXI_SLAVE_SEED)
    ) ddr_mem (
        .clk(clk_in), .rst_n(rst), .axi(ddr_axi)
    );
    assign o_idle = rst && UUT.core_state == CORE_IDLE;
    assign o_running = rst && UUT.core_state == CORE_RUNNING;

    wire uut_clk = clk_in;

    always #(`CLOCK_PERIOD / 2) clk_in = ~clk_in;

    // Register probes: the regfile storage is LUTRAM without reset, so a
    // register not written since reset holds its reset value instead
    wire [31:0] core_reg_probes [0:NUM_CORES-1][0:31];

    genvar cg, rg;
    generate
        for (cg = 0; cg < NUM_CORES; cg = cg + 1) begin : probe_cores
            for (rg = 0; rg < 32; rg = rg + 1) begin : probe_regs
                assign core_reg_probes[cg][rg] =
                    UUT.smx.cores[cg].core.regfile.written[rg] ? UUT.smx.cores[cg].core.regfile.ram[rg] :
                    reg_reset_value(rg, cg);
            end
        end
    endgenerate

    initial begin
        clk_in = 1'b0;
        rst = 1'b0;

        if (!$value$plusargs("TEST_IDX=%d", test_idx)) begin
            test_idx = 1;
        end

        has_test_end = $value$plusargs("TEST_END=%d", test_end);

        $display("[INFO] =================================================");
        $display("[INFO]  Starting GPGPU SMX-Only Test Suite");
        $display("[INFO]  NUM_CORES = %0d", NUM_CORES);
        $display("[INFO] =================================================");

        forever begin
            if (has_test_end && test_idx > test_end) begin
                $display("\n[INFO] Reached requested TEST_END=%0d. Simulation finished successfully!", test_end);
                #(`CLOCK_PERIOD * 20);
                $finish;
                // The simulator can continue this time slot after $finish.
                break;
            end

            $sformat(prog_file, "cases/test%0d/program.mem", test_idx);
            $sformat(data_file, "cases/test%0d/data.mem", test_idx);

            fd = $fopen(prog_file, "r");
            if (fd == 0) begin
                if (test_idx == 1)
                    $fatal(1, "[ERROR] No tests were found");
                else
                    $display("\n[INFO] Simulation finished successfully!");

                #(`CLOCK_PERIOD * 20);
                $finish;
                // The simulator can continue this time slot after $finish.
                break;
            end
            $fclose(fd);

            $display("\n[INFO] ---> Starting test %0d...", test_idx);

            // A case that uses DDR has an expected DDR file; it needs the backend.
            ddr_file = $sformatf("cases/test%0d/ddr.mem", test_idx);
            ddr_seed_file = $sformatf("cases/test%0d/ddr_seed.mem", test_idx);
            fd = $fopen(ddr_file, "r");
            has_ddr = fd != 0;
            if (has_ddr) $fclose(fd);
            if (has_ddr && DDR_ENABLE == 0) begin
                $display("  [INFO] Uses DDR: skipped without the DDR backend.");
                test_idx = test_idx + 1;
                continue;
            end

            // Clear expected arrays
            for (i = 0; i < DMEM_ENTRIES; i = i + 1)
                expected_data[i] = 32'b0;

            for (c = 0; c < NUM_CORES; c = c + 1)
                for (i = 0; i < 32; i = i + 1)
                    expected_regfile[c][i] = 32'b0;

            // Clear DUT memories directly
            for (i = 0; i < IMEM_ENTRIES; i = i + 1)
                UUT.instructionMemory.data[i] = 32'b0;

            for (i = 0; i < DMEM_ENTRIES; i = i + 1)
                UUT.memory_subsystem.bramBackend.dataMemory.data[i] = 32'b0;

            // Load IMEM directly, like old SMX test
            $readmemh(prog_file, UUT.instructionMemory.data);

            // Load expected final DMEM
            $readmemh(data_file, expected_data);

            // Load expected regfiles
            for (c = 0; c < NUM_CORES; c = c + 1) begin
                $sformat(reg_file, "cases/test%0d/regfile_c%0d.mem", test_idx, c);
                $readmemh(reg_file, temp_regfile);

                for (i = 0; i < 32; i = i + 1)
                    expected_regfile[c][i] = temp_regfile[i];
            end

            $sformat(trace_file, "cases/test%0d/trace.csv", test_idx);
            fd_trace = $fopen(trace_file, "w");

            // Reset
            rst = 1'b0;
            repeat (10) @(posedge uut_clk);
            ddr_mem.clear();
            fd = $fopen(ddr_seed_file, "r");
            if (fd != 0) begin
                $fclose(fd);
                ddr_mem.load_words(ddr_seed_file);
            end
            rst = 1'b1;
            repeat (10) @(posedge uut_clk);

            /*
             * Bypass ExecutionController for SMX-only testing.
             *
             * This forces the GPGPU top-level muxes to give memory ownership
             * to the SMX and makes o_running reflect running state.
             */
            @(negedge UUT.clk);
            force UUT.core_state = ControlPkg::CORE_RUNNING;

            cycle_count = 0;

            while (UUT.core_complete !== 1'b1 &&
                   cycle_count < `TEST_TIMEOUT_CYCLES) begin

                @(posedge uut_clk);
                cycle_count = cycle_count + 1;

                $fdisplay(fd_trace, "%5d,%8h,%8h,%8h,%8h,%8h",
                    cycle_count,
                    UUT.smx.program_counter,
                    UUT.smx.ifid_program_counter,
                    UUT.smx.idex.program_counter,
                    UUT.smx.cores[0].core.exmem.program_counter,
                    UUT.smx.cores[0].core.memwb.program_counter
                );
            end

            $fclose(fd_trace);
            // Do not change the forced run state in the active writeback edge.
            @(negedge uut_clk);
            force UUT.core_state = ControlPkg::CORE_IDLE;

            if (cycle_count >= `TEST_TIMEOUT_CYCLES) begin
                $fatal(1, "Test %0d reached timeout of %0d cycles!",
                         test_idx, `TEST_TIMEOUT_CYCLES);
            end else begin
                $display("  [INFO] Test %0d finished in %0d cycles!",
                         test_idx, cycle_count);
            end

            repeat (10) @(posedge uut_clk);

            // Performance counters, read directly (this bench drives the run
            // state itself): every RUNNING cycle is in exactly one warp leaf
            perf_errors = 0;
            begin
                // Sized by the register map's slots, so the counter enums index them
                longint unsigned global_count [PERF_GLOBAL_SLOTS];
                longint unsigned leaf_sum, running;
                PerfPkg::perf_warp_leaf_t leaf;
                for (int unsigned c = 0; c < PerfPkg::PERF_GLOBAL_COUNT; c++)
                    global_count[c] = UUT.perf.global_count[c];
                leaf_sum = 0;
                running = global_count[PerfPkg::PERF_KERNEL_CYCLES]
                        - global_count[PerfPkg::PERF_RUN_RESET]
                        - global_count[PerfPkg::PERF_RUN_DRAIN];
                $write("  [PERF] RUNNING %0d:", running);
                for (int unsigned l = 0; l < PerfPkg::PERF_WARP_LEAF_COUNT; l++) begin
                    leaf_sum += UUT.perf.warp_count[0][l];
                    leaf = PerfPkg::perf_warp_leaf_t'(l);
                    if (UUT.perf.warp_count[0][l] != 0)
                        $write(" %s=%0d", leaf.name(), UUT.perf.warp_count[0][l]);
                end
                $write("\n");
                if (leaf_sum != running) begin
                    $display("  [ERROR] Warp leaves sum to %0d, not the %0d RUNNING cycles", leaf_sum, running);
                    perf_errors++;
                end
            end

            // Compare regfiles
            reg_errors = 0;

            for (c = 0; c < NUM_CORES; c = c + 1) begin
                for (i = 0; i < 32; i = i + 1) begin
                    if (i == 31) begin
                        if (core_reg_probes[c][i] !== c) begin
                            $display("  [ERROR] Core %0d Reg %0d (TXD): Expected %0h, Found %h",
                                     c, i, c, core_reg_probes[c][i]);
                            reg_errors = reg_errors + 1;
                        end
                    end else begin
                        if (core_reg_probes[c][i] !== expected_regfile[c][i]) begin
                            $display("  [ERROR] Core %0d Reg %0d: Expected %h, Found %h",
                                     c, i, expected_regfile[c][i], core_reg_probes[c][i]);
                            reg_errors = reg_errors + 1;
                        end
                    end
                end
            end

            // Compare DMEM directly
            data_errors = 0;

            for (i = 0; i < DMEM_ENTRIES; i = i + 1) begin
                if (UUT.memory_subsystem.bramBackend.dataMemory.data[i] !== expected_data[i]) begin
                    $display("  [ERROR] Data memory Address %0d: Expected %h, Found %h",
                             i, expected_data[i], UUT.memory_subsystem.bramBackend.dataMemory.data[i]);
                    data_errors = data_errors + 1;
                end
            end

            if (!ddr_mem.idle()) begin
                $display("  [ERROR] A DDR transaction is still open after completion");
                data_errors = data_errors + 1;
            end
            if (has_ddr) begin
                ddr_errors = ddr_mem.check_words(ddr_file);
                data_errors = data_errors + ddr_errors;
            end

            if (reg_errors == 0 && data_errors == 0 && perf_errors == 0) begin
                $display("  [SUCCESS] Test %0d is correct across all %0d cores!",
                         test_idx, NUM_CORES, cycle_count);
            end else begin
                $display("  [WARNING] Test %0d failed. Reg errors: %0d, Data errors: %0d, Perf errors: %0d",
                         test_idx, reg_errors, data_errors, perf_errors);
                $fatal(1, "  [WARNING] Halting simulation due to SMX-only GPGPU test failure.");
                
            end

            test_idx = test_idx + 1;
        end
    end

    initial begin
        // Waveforms are dumped only when the runner passes +DUMP_FILE.
        if ($value$plusargs("DUMP_FILE=%s", dump_file)) begin
            $dumpfile(dump_file);
            $dumpvars(0, tb_GPGPU_smx_only);
        end
    end

endmodule
