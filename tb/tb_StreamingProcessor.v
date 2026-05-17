`timescale 1ns/1ps
`include "constants.vh"

`define CLOCK_PERIOD 10
`define TEST_TIMEOUT_CYCLES 1500

module tb_StreamingProcessor ();
    // Configure the number of cores to test
    parameter NUM_CORES = 4;

    reg clk, rst;
    reg dummy_wen;
    wire [2:0] o_leds;
    wire o_kernel_complete;
    
    // Expected results arrays
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

    // Instantiation of the UUT
    StreamingMultiprocessor #(
        .NUM_CORES(NUM_CORES)
    ) UUT (
        .i_clk(clk), 
        .rst(rst), 
        .i_dummy_wen(dummy_wen), 
        .o_leds(o_leds),
        .o_kernel_complete(o_kernel_complete)
    );

    // =========================================================================
    // Icarus Verilog Workaround: Probe Arrays
    // We cannot dynamically index instances (e.g. UUT.cores[c].core...) inside a 
    // standard procedural for-loop. We use generate blocks to map the inner 
    // register file arrays to a 2D wire array we can easily index.
    // =========================================================================
    wire [31:0] core_reg_probes [0:NUM_CORES-1][0:31];
    
    genvar cg, rg;
    generate
        for (cg = 0; cg < NUM_CORES; cg = cg + 1) begin : probe_cores
            for (rg = 0; rg < 32; rg = rg + 1) begin : probe_regs
                assign core_reg_probes[cg][rg] = UUT.cores[cg].core.regfile.data[rg];
            end
        end
    endgenerate

    // Clock Generation
    always #(`CLOCK_PERIOD / 2) clk = ~clk;

    initial begin
        clk = 1;
        rst = 0;
        dummy_wen = 0;
        // Do NOT put "test_idx = 1;" outside of this if-statement.
        if (!$value$plusargs("TEST_IDX=%d", test_idx)) begin
            test_idx = 1;
        end
        
        $display("=================================================");
        $display(" Starting the Multi-Core Test Suite");
        $display("=================================================");

        forever begin
            // 1. Find the path of the tests dynamically
            $sformat(prog_file, "test%0d/program.mem", test_idx);
            $sformat(data_file, "test%0d/data.mem", test_idx);

            // 2. If the test doesn't exist, break the loop
            fd = $fopen(prog_file, "r");
            if (fd == 0) begin
                if (test_idx == 1) 
                    $display("[ERROR] No tests were found");
                else 
                    $display("\nSimulation finished successfully!");
                #(`CLOCK_PERIOD * `TEST_TIMEOUT_CYCLES);
                $finish;
            end
            $fclose(fd);

            $display("\n---> Starting test %0d...", test_idx);

            // 3. Clear the memories
            for (i=0; i<`DMEM_ENTRIES; i=i+1) UUT.dataMemory.data[i] = 32'b0;
            for (i=0; i<`DMEM_ENTRIES; i=i+1) expected_data[i] = 32'b0;
            for (c=0; c<NUM_CORES; c=c+1)
                for (i=0; i<32; i=i+1) expected_regfile[c][i] = 32'b0;

            // Wait until runtime to let internal registers reset cleanly via RST, 
            // rather than forcefully clearing them from the TB.

            // 4. Load memories
            $readmemh(prog_file, UUT.instructionMemory.data);
            $readmemh(data_file, expected_data);
            
            for (c=0; c<NUM_CORES; c=c+1) begin
                $sformat(reg_file, "test%0d/regfile_c%0d.mem", test_idx, c);
                
                // Read into the 1D temp array first
                $readmemh(reg_file, temp_regfile); 
                
                // Copy the contents into the 2D array
                for (i=0; i<32; i=i+1) begin
                    expected_regfile[c][i] = temp_regfile[i];
                end
            end
            
            // 4.5. Open Trace File
            $sformat(trace_file, "test%0d/trace.csv", test_idx);
            fd_trace = $fopen(trace_file, "w");

            // 5. Reset Sequence
            rst = 0;
            #(`CLOCK_PERIOD * 5.75);
            rst = 1;

            // 6. Test execution cycle loop (Now with both completion check AND timeout)
            cycle_count = 0;
            while (o_kernel_complete !== 1'b1 && cycle_count < `TEST_TIMEOUT_CYCLES) begin
                #(`CLOCK_PERIOD);
                cycle_count = cycle_count + 1;

                if (rst == 1) begin
                    $fdisplay(fd_trace, "%5d,%8h,%8h,%8h,%8h,%8h", 
                        cycle_count,
                        UUT.program_counter,               
                        UUT.ifid_program_counter,          
                        UUT.idex_program_counter,          
                        UUT.cores[0].core.exmem_program_counter,  
                        UUT.cores[0].core.memwb_program_counter   
                    );
                end
            end
            $fclose(fd_trace);

            if (cycle_count >= `TEST_TIMEOUT_CYCLES) begin
                $display("  [WARNING] Test %0d reached timeout of %0d cycles!", test_idx, `TEST_TIMEOUT_CYCLES);
            end

            // Leave some cycles pass to let pipeline drain and clearly separate tests in waveforms
            #(`CLOCK_PERIOD * 10);

            // 7. Compare the Regfiles for ALL cores
            reg_errors = 0;
            for (c = 0; c < NUM_CORES; c = c + 1) begin
                for (i = 0; i < 32; i = i + 1) begin
                    // Account for TXD_REGISTER (R31) which holds the hardcoded CORE_ID
                    if (i == 31) begin 
                        if (core_reg_probes[c][i] !== c) begin
                            $display("  [Error] Core %0d Reg %0d (TXD): Expected %0h, Found %h", 
                                     c, i, c, core_reg_probes[c][i]);
                            reg_errors = reg_errors + 1;
                        end
                    end else begin
                        if (core_reg_probes[c][i] !== expected_regfile[c][i]) begin
                            $display("  [Error] Core %0d Reg %0d: Expected %h, Found %h", 
                                     c, i, expected_regfile[c][i], core_reg_probes[c][i]);
                            reg_errors = reg_errors + 1;
                        end
                    end
                end
            end

            // 8. Compare Global Shared Data Memory
            data_errors = 0;
            for (i = 0; i < `DMEM_ENTRIES; i = i + 1) begin
                if (UUT.dataMemory.data[i] !== expected_data[i]) begin
                    $display("  [Error] Data memory Address %0d: Expected %h, Found %h", 
                             i, expected_data[i], UUT.dataMemory.data[i]);
                    data_errors = data_errors + 1;
                end
            end

            // 9. Final Verdict
            if (reg_errors == 0 && data_errors == 0) begin
                $display("  [PASS] Test %0d is correct across all %0d cores! (Finished in %0d cycles)", test_idx, NUM_CORES, cycle_count);
            end else begin
                $display("  [FAIL] Test %0d failed. (Reg errors: %0d, Data errors: %0d)", 
                    test_idx, reg_errors, data_errors);
                
                // FIX 2: Crash the simulation so Make/Bash knows it actually failed!
                $fatal(1, "Halting simulation due to standard test failure.");
            end

            test_idx = test_idx + 1;
        end
    end

    // =========================================================================
    // Waveform Dumping
    // =========================================================================
    initial begin
        $dumpfile("dumpfile.vcd");
        $dumpvars(0, tb_StreamingProcessor);
    end

    // // Dump multi-core 2D Arrays without throwing Scope Index errors
    // genvar d, c_dump;
    // generate
    //     for (d = 0; d < 32; d = d + 1) begin : dump_mems
    //         initial begin
    //             #0;
    //             $dumpvars(0, tb_StreamingProcessor.UUT.instructionMemory.data[d]);
    //             $dumpvars(0, tb_StreamingProcessor.UUT.dataMemory.data[d]);
    //         end
    //     end
    //     for (c_dump = 0; c_dump < NUM_CORES; c_dump = c_dump + 1) begin : dump_cores
    //         for (d = 0; d < 32; d = d + 1) begin : dump_regs
    //             initial begin
    //                 #0;
    //                 $dumpvars(0, tb_StreamingProcessor.UUT.cores[c_dump].core.regfile.data[d]);
    //             end
    //         end
    //     end
    // endgenerate

endmodule