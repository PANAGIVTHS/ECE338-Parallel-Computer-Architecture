`timescale 1ns / 1ps

module tb_GPGPU_e2e();

    //==============================================
    // CLOCK AND TIMING PARAMETERS
    //==============================================
    // Assuming a 10MHz input clock (100ns period)
    localparam CLK_PERIOD = 100; 
    
    // Change this to perfectly match your hardware's baud rate!
    // Using 1600ns for the 625,000 Baud custom rate we discussed.
    localparam BIT_PERIOD = 1600; 

    reg  clk;
    reg  rst;
    reg  uart_rx;
    wire uart_tx;

    //==============================================
    // INSTANTIATE THE TOP-LEVEL GPU
    //==============================================
    GPGPU UUT (
        .i_clk(clk),
        .i_rst(rst),
        .i_uart_rx(uart_rx),
        .o_uart_tx(uart_tx)
    );

    //==============================================
    // CLOCK GENERATION
    //==============================================
    always #(CLK_PERIOD / 2) clk = ~clk;

    //==============================================
    // UART TRANSMIT TASKS
    //==============================================
    task send_uart_byte(input [7:0] data_to_send);
        integer i;
        begin
            uart_rx = 1'b0; // Start Bit
            #(BIT_PERIOD);
            for (i = 0; i < 8; i = i + 1) begin
                uart_rx = data_to_send[i];
                #(BIT_PERIOD);
            end
            uart_rx = 1'b1; // Stop Bit
            #(BIT_PERIOD);
            #(BIT_PERIOD * 2); // Idle buffer
        end
    endtask

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
    integer w; 

    initial begin
        $display("=================================================");
        $display(" Starting GPGPU IMEM Load Verification Test");
        $display("=================================================");

        // 1. Initialize
        clk = 0;
        rst = 0;
        uart_rx = 1;

        // 2. Apply Reset
        #(CLK_PERIOD * 10);
        rst = 1;
        #(CLK_PERIOD * 10);

        $display("[System] Booting. Sending 1024 words to Host Controller...");

        // 3. Send the Program Payload
        for (w = 0; w < 1024; w = w + 1) begin
            
            // Send our test instructions for the first few words
            if (w == 0)      send_uart_word(32'h00500093); // Test Word 0
            else if (w == 1) send_uart_word(32'h00a00113); // Test Word 1
            else if (w == 2) send_uart_word(32'hDEADBEEF); // Test Word 2
            else send_uart_word(32'h11111111); 
            
            if (w % 256 == 0 && w > 0) $display("  ... Sent %0d words", w);
        end

        $display("[System] Payload delivered. Waiting for Host Controller to enter RUN state...");

        // 4. Wait for the LOAD phase to finish
        // We wait for the HostController to hit 2'b01 (RUN state), which happens
        // immediately after the 1024th word is fully received.
        wait(UUT.host_controller.current_state == 2'b01);
        $display("[System] Host Controller successfully transitioned to RUN state!");

        //==============================================
        // 5. BACKDOOR MEMORY VERIFICATION (IMEM)
        //==============================================
        $display("=================================================");
        $display(" Verifying Instruction Memory (IMEM) Contents:");

        // Check Word 0
        if (UUT.instructionMemory.data[0] == 32'h00500093) begin
            $display("  [PASS] Address 0 holds 00500093.");
        end else begin
            $display("  [FAIL] Address 0 holds %h, expected 00500093.", UUT.instructionMemory.data[0]);
        end

        // Check Word 1
        if (UUT.instructionMemory.data[1] == 32'h00a00113) begin
            $display("  [PASS] Address 1 holds 00a00113.");
        end else begin
            $display("  [FAIL] Address 1 holds %h, expected 00a00113.", UUT.instructionMemory.data[1]);
        end

        // Check Word 2
        if (UUT.instructionMemory.data[2] == 32'hDEADBEEF) begin
            $display("  [PASS] Address 2 holds DEADBEEF.");
        end else begin
            $display("  [FAIL] Address 2 holds %h, expected DEADBEEF.", UUT.instructionMemory.data[2]);
        end

        // Check the very last padded word to ensure the whole 1024-word block loaded
        if (UUT.instructionMemory.data[1023] == 32'h11111111) begin
            $display("  [PASS] Address 1023 holds 11111111.");
        end else begin
            $display("  [FAIL] Address 1023 holds %h, expected 11111111.", UUT.instructionMemory.data[1023]);
        end

        $display("=================================================");
        $display(" IMEM Verification Complete.");
        $display("=================================================");
        $finish;
    end

    initial begin
        $dumpfile("gpgpu_e2e.vcd");
        $dumpvars(0, tb_GPGPU_e2e);
    end

endmodule