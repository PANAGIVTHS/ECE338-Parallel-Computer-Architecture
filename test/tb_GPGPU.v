`timescale 1ns/1ps
`include "constants.vh"

`define CLOCK_PERIOD 10
`define TEST_TIMEOUT_CYCLES 1500

module tb_GPGPU_smx_only ();

    parameter NUM_CORES = 33;

    reg clk_in, rst;

    wire o_loading;
    wire o_running;
    wire o_dumping;

    wire [31:0] host_rdata;
    wire host_busy;
    wire host_done;

    // Unused host interface
    reg [2:0]  host_command;
    reg        host_command_valid;
    reg [31:0] host_address;
    reg [31:0] host_wdata;

    reg [31:0] expected_data [0:`DMEM_ENTRIES-1];
    reg [31:0] expected_regfile [0:NUM_CORES-1][0:31];
    reg [31:0] temp_regfile [0:31];

    integer i, c;
    integer test_idx;
    integer fd;
    integer data_errors, reg_errors;
    integer cycle_count;
    integer fd_trace;

    reg [8*255:0] prog_file;
    reg [8*255:0] data_file;
    reg [8*255:0] reg_file;
    reg [8*255:0] trace_file;

    GPGPU #(
        .SP_PER_SM(NUM_CORES)
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

    // If clk_wiz_0 sim model works, use internal generated clock.
    // If not, replace UUT clk_wiz in RTL with assign clk = clk_in for simulation.
    wire uut_clk = UUT.clk;

    always #(`CLOCK_PERIOD / 2) clk_in = ~clk_in;

    // Register probes through new hierarchy
    wire [31:0] core_reg_probes [0:NUM_CORES-1][0:31];

    genvar cg, rg;
    generate
        for (cg = 0; cg < NUM_CORES; cg = cg + 1) begin : probe_cores
            for (rg = 0; rg < 32; rg = rg + 1) begin : probe_regs
                assign core_reg_probes[cg][rg] =
                    UUT.smx.cores[cg].core.regfile.data[rg];
            end
        end
    endgenerate

    initial begin
        clk_in = 1'b0;
        rst = 1'b0;

        host_command       = 3'b0;
        host_command_valid = 1'b0;
        host_address       = 32'b0;
        host_wdata         = 32'b0;
        force UUT.host_controller.o_host_address = 32'h10;

        if (!$value$plusargs("TEST_IDX=%d", test_idx)) begin
            test_idx = 1;
        end

        $display("[INFO] =================================================");
        $display("[INFO]  Starting GPGPU SMX-Only Test Suite");
        $display("[INFO]  NUM_CORES = %0d", NUM_CORES);
        $display("[INFO] =================================================");

        forever begin
            $sformat(prog_file, "tests/test%0d/program.mem", test_idx);
            $sformat(data_file, "tests/test%0d/data.mem", test_idx);

            fd = $fopen(prog_file, "r");
            if (fd == 0) begin
                if (test_idx == 1)
                    $display("[ERROR] No tests were found");
                else
                    $display("\n[INFO] Simulation finished successfully!");

                #(`CLOCK_PERIOD * 20);
                $finish;
            end
            $fclose(fd);

            $display("\n[INFO] ---> Starting test %0d...", test_idx);

            // Clear expected arrays
            for (i = 0; i < `DMEM_ENTRIES; i = i + 1)
                expected_data[i] = 32'b0;

            for (c = 0; c < NUM_CORES; c = c + 1)
                for (i = 0; i < 32; i = i + 1)
                    expected_regfile[c][i] = 32'b0;

            // Clear DUT memories directly
            for (i = 0; i < `IMEM_ENTRIES; i = i + 1)
                UUT.instructionMemory.data[i] = 32'b0;

            for (i = 0; i < `DMEM_ENTRIES; i = i + 1)
                UUT.dataMemory.data[i] = 32'b0;

            // Load IMEM directly, like old SMX test
            $readmemh(prog_file, UUT.instructionMemory.data);

            // Load expected final DMEM
            $readmemh(data_file, expected_data);

            // Load expected regfiles
            for (c = 0; c < NUM_CORES; c = c + 1) begin
                $sformat(reg_file, "tests/test%0d/regfile_c%0d.mem", test_idx, c);
                $readmemh(reg_file, temp_regfile);

                for (i = 0; i < 32; i = i + 1)
                    expected_regfile[c][i] = temp_regfile[i];
            end

            $sformat(trace_file, "tests/test%0d/trace.csv", test_idx);
            fd_trace = $fopen(trace_file, "w");

            // Reset
            rst = 1'b0;
            repeat (10) @(posedge uut_clk);
            rst = 1'b1;
            repeat (10) @(posedge uut_clk);

            /*
             * Bypass HostController for SMX-only testing.
             *
             * This forces the GPGPU top-level muxes to give memory ownership
             * to the SMX and makes o_running reflect running state.
             */
            @(negedge UUT.clk);
            force UUT.core_state = `CORE_RUNNING;

            cycle_count = 0;

            while (UUT.core_complete !== 1'b1 &&
                   cycle_count < `TEST_TIMEOUT_CYCLES) begin

                @(posedge uut_clk);
                cycle_count = cycle_count + 1;

                $fdisplay(fd_trace, "%5d,%8h,%8h,%8h,%8h,%8h",
                    cycle_count,
                    UUT.smx.program_counter,
                    UUT.smx.ifid_program_counter,
                    UUT.smx.idex_program_counter,
                    UUT.smx.cores[0].core.exmem_program_counter,
                    UUT.smx.cores[0].core.memwb_program_counter
                );
            end

            $fclose(fd_trace);
            force UUT.core_state = `CORE_DUMPING;

            if (cycle_count >= `TEST_TIMEOUT_CYCLES) begin
                $display("  [WARNING] Test %0d reached timeout of %0d cycles!",
                         test_idx, `TEST_TIMEOUT_CYCLES);
            end else begin
                $display("  [INFO] Test %0d finished in %0d cycles!",
                         test_idx, cycle_count);
            end

            repeat (10) @(posedge uut_clk);

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

            for (i = 0; i < `DMEM_ENTRIES; i = i + 1) begin
                if (UUT.dataMemory.data[i] !== expected_data[i]) begin
                    $display("  [ERROR] Data memory Address %0d: Expected %h, Found %h",
                             i, expected_data[i], UUT.dataMemory.data[i]);
                    data_errors = data_errors + 1;
                end
            end

            if (reg_errors == 0 && data_errors == 0) begin
                $display("  [INFO] Test %0d is correct across all %0d cores!",
                         test_idx, NUM_CORES, cycle_count);
            end else begin
                $display("  [WARNING] Test %0d failed. Reg errors: %0d, Data errors: %0d",
                         test_idx, reg_errors, data_errors);
                $fatal(1, "  [WARNING] Halting simulation due to SMX-only GPGPU test failure.");
                
            end

            test_idx = test_idx + 1;
        end
    end

    initial begin
        $dumpfile("dumpfile.vcd");
        $dumpvars(0, tb_GPGPU_smx_only);
    end

endmodule