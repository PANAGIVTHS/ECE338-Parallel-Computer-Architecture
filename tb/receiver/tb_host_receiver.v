`timescale 1ns / 1ps

module tb_host_receiver();

    // 10MHz Clock
    localparam CLK_PERIOD = 100; 
    // 115200 Baud Rate -> 8680ns per bit
    localparam BIT_PERIOD = 1600; 

    reg clk;
    reg rst;
    reg core_complete;
    reg uart_rx;

    wire uart_tx;
    wire core_run;
    wire core_clear;
    
    wire [$clog2(`IMEM_ENTRIES)-1:0] imem_addr;
    wire [31:0] imem_wdata;
    wire imem_wen;

    // Dummy wires for Data Memory / Regfile (since we are only testing RX)
    wire [9:0] dmem_addr;
    wire [4:0] reg_addr;
    reg  [31:0] dummy_dmem_rdata = 32'b0;
    reg  [31:0] dummy_reg_rdata = 32'b0;

    //==============================================
    // INSTANTIATE THE HOST CONTROLLER
    //==============================================
    HostController UUT (
        .i_clk(clk),
        .i_rst(rst),
        .i_core_complete(core_complete),
        .i_uart_rx(uart_rx),
        .o_uart_tx(uart_tx),
        .o_core_run(core_run),
        .o_core_clear(core_clear),
        .o_imem_addr(imem_addr),
        .o_imem_wdata(imem_wdata),
        .o_imem_wen(imem_wen),
        .o_dmem_addr(dmem_addr),
        .i_dmem_rdata(dummy_dmem_rdata),
        .o_reg_addr(reg_addr),
        .i_reg_rdata(dummy_reg_rdata)
    );

    //==============================================
    // CLOCK GENERATION
    //==============================================
    always #(CLK_PERIOD / 2) clk = ~clk;

    //==============================================
    // UART TRANSMIT TASK (Simulates the PC)
    //==============================================
    task send_uart_byte(input [7:0] data_to_send);
        integer i;
        begin
            uart_rx = 1'b0; // Start Bit
            #(BIT_PERIOD);
            for (i = 0; i < 8; i = i + 1) begin
                uart_rx = data_to_send[i]; // Data Bits (LSB first)
                #(BIT_PERIOD);
            end
            uart_rx = 1'b1; // Stop Bit
            #(BIT_PERIOD);
            #(BIT_PERIOD * 2); // Idle buffer
        end
    endtask

    // Helper task to send a full 32-bit word (Big Endian)
    task send_uart_word(input [31:0] word_to_send);
        begin
            send_uart_byte(word_to_send[31:24]);
            send_uart_byte(word_to_send[23:16]);
            send_uart_byte(word_to_send[15:8]);
            send_uart_byte(word_to_send[7:0]);
        end
    endtask

    //==============================================
    // MAIN TEST SEQUENCE
    //==============================================
    integer w; // Loop variable

    initial begin
        $display("=================================================");
        $display(" Starting Host Controller RX Test");
        $display(" Expected: 1024 Words (4096 Bytes) to load into IMEM");
        $display("=================================================");

        clk = 0;
        rst = 0;
        uart_rx = 1; // Idle high
        core_complete = 0;

        // Apply Reset
        #(CLK_PERIOD * 10);
        rst = 1;
        #(CLK_PERIOD * 10);

        // Send all 1024 Words using a loop!
        // We will just send the loop index 'w' as the data so you can 
        // watch it count up perfectly in the console.
        for (w = 0; w < 1024; w = w + 1) begin
            send_uart_word(w);
            
            // Print a progress update every 256 words so you know it's not frozen
            if (w % 256 == 0) begin
                $display("[Time: %0t] Sent %0d / 1024 words...", $time, w);
            end
        end

        $display("\n[Time: %0t] Finished sending 1024 words. Waiting for FSM...", $time);

        // Wait a little bit to let FSM transition
        #(CLK_PERIOD * 50);

        if (core_run) begin
            $display("\n[SUCCESS] Host Controller transitioned to RUN state!");
        end else begin
            $display("\n[FAIL] Host Controller did not enter RUN state.");
        end

        $display("=================================================");
        $display(" Simulation Complete!");
        $display("=================================================");
        $finish;
    end

    //==============================================
    // SELF-CHECKING MONITOR
    //==============================================
    always @(posedge clk) begin
        if (imem_wen) begin
            $display("   --> [BRAM WRITE] Address: %0d | Data: %h", imem_addr, imem_wdata);
        end
    end

    //==============================================
    // WAVEFORM DUMP
    //==============================================
    initial begin
        $dumpfile("host_rx_dump.vcd");
        $dumpvars(0, tb_host_receiver);
    end

endmodule