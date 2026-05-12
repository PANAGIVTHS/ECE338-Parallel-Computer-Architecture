`timescale 1ns/1ps

`define CLOCK_PERIOD 10
`define TEST_TIMEOUT_CYCLES 200

module tb_StreamingProcessor ();
    reg clk, rst;
    reg dummy_wen;
    wire [2:0] o_leds;
    
    // Expected results arrays
    reg [31:0] expected_data [0:1023];
    reg [31:0] expected_regfile [0:31];

    integer i;
    integer test_idx;
    integer fd;
    integer data_errors, reg_errors;
    integer cycle_count;
    integer fd_trace;

    reg [8*255:0] prog_file;
    reg [8*255:0] data_file;
    reg [8*255:0] reg_file;
    reg [8*255:0] trace_file;

    // UUT is now the StreamingMultiprocessor
    StreamingMultiprocessor UUT (
        .i_clk(clk), 
        .rst(rst), 
        .i_dummy_wen(dummy_wen), 
        .o_leds(o_leds)
    );

    // Clock
    always #(`CLOCK_PERIOD / 2) clk = ~clk;

    initial begin
        clk = 1;
        rst = 0;
        dummy_wen = 0;
        test_idx = 1;

        $display("=================================================");
        $display(" Starting the test suite");
        $display("=================================================");

        forever begin
            // 1. Find the path of the tests dynamically
            $sformat(prog_file, "test%0d/program.mem", test_idx);
            $sformat(data_file, "test%0d/data.mem", test_idx);
            $sformat(reg_file, "test%0d/regfile.mem", test_idx);

            // 2. If the test doesn't exist, break the loop
            fd = $fopen(prog_file, "r");
            if (fd == 0) begin
                if (test_idx == 1) 
                    $display("[ERROR] No tests were found");
                else 
                    $display("\nSimulation finished!");
                #(`CLOCK_PERIOD * `TEST_TIMEOUT_CYCLES);
                $finish;
            end
            $fclose(fd);

            $display("\n---> Starting the tests %0d...", test_idx);

            // 3. Clear the memories
            for (i=0; i<1024; i=i+1) UUT.dataMemory.data[i] = 32'b0;
            for (i=0; i<1024; i=i+1) expected_data[i] = 32'b0;
            for (i=0; i<32; i=i+1) expected_regfile[i] = 32'b0;
            for (i=0; i<32; i=i+1) UUT.cores[0].core.regfile.data[i] = 32'b0;

            // 4. Load memories
            $readmemh(prog_file, UUT.instructionMemory.data);
            $readmemh(data_file, expected_data);
            $readmemh(reg_file, expected_regfile);

            $sformat(trace_file, "test%0d/trace.csv", test_idx);

            fd_trace = $fopen(trace_file, "w");
            if (fd_trace == 0) begin
                $display("  [ERROR] Could not create trace file: %s", trace_file);
            end

            // 5. Reset
            rst = 0;
            #(`CLOCK_PERIOD * 5.75);
            rst = 1;

            // 6. Timeout mechanism and output to csv
            cycle_count = 0;
            while (cycle_count < `TEST_TIMEOUT_CYCLES) begin
                #(`CLOCK_PERIOD);
                cycle_count = cycle_count + 1;

                if (rst == 1) begin
                    $fdisplay(fd_trace, "%5d,%8h,%8h,%8h,%8h,%8h", 
                        cycle_count,
                        UUT.program_counter,               // IF (in SM)
                        UUT.ifid_program_counter,          // ID (in SM)
                        UUT.idex_program_counter,          // EX (in SM, passed to SP)
                        UUT.cores[0].core.exmem_program_counter,  // MEM (in SP)
                        UUT.cores[0].core.memwb_program_counter   // WB (in SP)
                    );
                end
            end

            $fclose(fd_trace);

            if (cycle_count >= `TEST_TIMEOUT_CYCLES) 
                $display("  [WARNING] Test %0d timed out!", test_idx);

            // 7. Compare the regfile
            reg_errors = 0;
            for (i = 0; i < 32; i = i + 1) begin
                // Updated path to regfile inside core_0
                if (UUT.cores[0].core.regfile.data[i] !== expected_regfile[i]) begin
                    $display("  [Error] Reg %0d: Expected %h, Found %h", 
                            i, expected_regfile[i], UUT.cores[0].core.regfile.data[i]);
                    reg_errors = reg_errors + 1;
                end
            end

            // 8. Compare Data Memory
            data_errors = 0;
            for (i = 0; i < 1024; i = i + 1) begin
                if (UUT.dataMemory.data[i] !== expected_data[i]) begin
                    $display("  [Error] Data memory Address %0d: Expected %h, Found %h", 
                             i, expected_data[i], UUT.dataMemory.data[i]);
                    data_errors = data_errors + 1;
                end
            end

            // 9. Test result
            if (reg_errors == 0 && data_errors == 0)
                $display("  [PASS] Test %0d is correct!", test_idx);
            else
                $display("  [FAIL] Test %0d failed. (Reg errors: %0d, Data errors: %0d)", 
                    test_idx, reg_errors, data_errors);

            test_idx = test_idx + 1;
        end
    end

    //! Waveform
    initial begin
        $dumpfile("dumpfile.vcd");
        
        // Dumps all standard wires and registers (including addresses and live crossbar data)
        $dumpvars(0, tb_StreamingProcessor);
    end

    // Use a compile-time generate block to dump the 2D memory arrays
    // This perfectly bypasses the Icarus Verilog "Scope index is not constant" error!
    genvar d;
    generate
        for (d = 0; d < 32; d = d + 1) begin : dump_arrays
            initial begin
                // Dumps the first 32 words of Instruction and Data memory
                $dumpvars(0, tb_StreamingProcessor.UUT.instructionMemory.data[d]);
                $dumpvars(0, tb_StreamingProcessor.UUT.dataMemory.data[d]);
                
                // Dumps all 32 registers of Core 0
                $dumpvars(0, tb_StreamingProcessor.UUT.cores[0].core.regfile.data[d]);
            end
        end
    endgenerate
endmodule