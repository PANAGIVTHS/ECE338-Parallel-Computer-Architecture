`timescale 1ns/1ps

`define CLOCK_PERIOD 10

module tb_StreamingProcessor ();
    reg clk, rst;
    integer i;

    initial begin
        clk = 0;
        rst = 0;
        #(`CLOCK_PERIOD * 2.75) rst = 1; //! Reset for 2.75 cycles
        #(`CLOCK_PERIOD * 10) $finish;
    end

    always #`CLOCK_PERIOD clk = ~clk;

    StreamingProcessor UUT (.clk(clk), .rst(rst));

    //! Initialize instruction memory
    initial begin
        $readmemh("program.hex", UUT.instructionMemory.data);
    end

    //! Program Counter
    always @(posedge clk) begin
        $display("PC: %4d", UUT.program_counter);
    end

    //! Waveform
    initial begin
        $dumpfile("dumpfile.vcd");
        $dumpvars(1, tb_StreamingProcessor);
        $dumpvars(1, tb_StreamingProcessor.UUT);
        $dumpvars(1, tb_StreamingProcessor.UUT.instructionMemory);
        for (i = 0; i < 32; i = i + 1) begin
            $dumpvars(1, tb_StreamingProcessor.UUT.instructionMemory.data[i]);
        end
    end
endmodule
