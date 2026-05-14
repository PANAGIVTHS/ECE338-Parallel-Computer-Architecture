`timescale 1ns / 1ps

module tb_GPGPU_e2e();

    //==============================================
    // SYSTEM CONSTANTS (72 MHz & 115200 Baud)
    //==============================================
    localparam CLK_PERIOD = 13.889;   // 1000 / 72 MHz
    localparam BIT_PERIOD = 8681;     // 1,000,000,000 / 115200 baud
    
    // Memory Sizes (Adjust these if your architecture uses different limits)
    localparam IMEM_WORDS = 1024; // 4096 Bytes
    localparam DMEM_WORDS = 1024; // 4096 Bytes
    localparam REG_WORDS  = 32;   // 128 Bytes

    reg clk;
    reg rst;
    reg uart_rx;
    wire uart_tx;

    //==============================================
    // INSTANTIATE YOUR TOP LEVEL GPGPU
    //==============================================
    // (Ensure the module name matches your actual top-level file)
    GPGPU UUT (
        .i_clk(clk),
        .i_rst(rst),
        .i_uart_rx(uart_rx),
        .o_uart_tx(uart_tx)
    );

    //==============================================
    // CLOCK GENERATION
    //==============================================
    always #(CLK_PERIOD / 2.0) clk = ~clk;

    //==============================================
    // MEMORY ARRAYS FOR TESTING
    //==============================================
    reg [31:0] expected_imem [0:IMEM_WORDS-1];
    reg [31:0] expected_dmem [0:DMEM_WORDS-1];
    reg [31:0] expected_reg  [0:REG_WORDS-1];

    //==============================================
    // UART TRANSMISSION TASKS (Simulates PC -> FPGA)
    //==============================================
    task send_uart_byte(input [7:0] tx_data);
        integer b;
        begin
            uart_rx = 1'b0; // Start bit
            #(BIT_PERIOD);
            
            for (b = 0; b < 8; b = b + 1) begin
                uart_rx = tx_data[b]; // Data bits (LSB first logically, but our vector index handles it)
                #(BIT_PERIOD);
            end
            
            uart_rx = 1'b1; // Stop bit
            #(BIT_PERIOD);
        end
    endtask

    task send_uart_word(input [31:0] tx_word);
        begin
            // Matches your UART receiver's Big-Endian buffer: [31:24], [23:16], [15:8], [7:0]
            send_uart_byte(tx_word[31:24]);
            send_uart_byte(tx_word[23:16]);
            send_uart_byte(tx_word[15:8]);
            send_uart_byte(tx_word[7:0]);
        end
    endtask

    //==============================================
    // UART RECEPTION TASKS (Simulates FPGA -> PC)
    //==============================================
    task receive_uart_byte(output reg [7:0] rx_data);
        integer b;
        begin
            wait (uart_tx == 1'b0); // Wait for the Start Bit to drop
            #(BIT_PERIOD / 2.0);    // Step to the center of the Start Bit
            
            if (uart_tx !== 1'b0) $display("ERROR: Start bit glitch!");
            #(BIT_PERIOD);          // Step to center of Bit 0

            for (b = 0; b < 8; b = b + 1) begin
                rx_data[b] = uart_tx;
                #(BIT_PERIOD);
            end
            
            if (uart_tx !== 1'b1) $display("ERROR: Stop bit missing! Framing Error.");
        end
    endtask

    task receive_uart_word(output reg [31:0] rx_word);
        reg [7:0] b3, b2, b1, b0;
        begin
            receive_uart_byte(b3);
            receive_uart_byte(b2);
            receive_uart_byte(b1);
            receive_uart_byte(b0);
            rx_word = {b3, b2, b1, b0};
        end
    endtask

    //==============================================
    // MAIN TEST SEQUENCE
    //==============================================
    integer i;
    reg [31:0] captured_word;
    integer errors;

    initial begin
        $display("=================================================");
        $display(" Starting End-to-End GPGPU Simulation...");
        $display("=================================================");
        
        // 1. Initialize Memories to ZERO
        for (i = 0; i < IMEM_WORDS; i = i + 1) expected_imem[i] = 32'b0;
        for (i = 0; i < DMEM_WORDS; i = i + 1) expected_dmem[i] = 32'b0;
        for (i = 0; i < REG_WORDS; i = i + 1)  expected_reg[i]  = 32'b0;

        // 2. Load the User's Provided Files
        // Make sure these text files are in your Vivado simulation directory!
        $readmemh("program.mem", expected_imem);
        $readmemh("data.mem", expected_dmem);
        $readmemh("regfile.mem", expected_reg);

        errors = 0;
        clk = 0;
        rst = 0;
        uart_rx = 1; // Idle state is HIGH

        #(CLK_PERIOD * 10);
        rst = 1;
        #(CLK_PERIOD * 10);

        //-----------------------------------------------------
        // PHASE 1: LOAD INSTRUCTIONS
        //-----------------------------------------------------
        $display("\n[PHASE 1] Sending %0d words of Instruction Memory to FPGA...", IMEM_WORDS);
        
        // We MUST send all 1024 words so the FSM byte_counter reaches 4096!
        // The first 26 words will be your code, the rest will be 0x00000000 (NOPs).
        for (i = 0; i < IMEM_WORDS; i = i + 1) begin
            send_uart_word(expected_imem[i]);
            
            // Print a progress update so you know the simulation hasn't frozen!
            if (i > 0 && i % 256 == 0) $display("  ...Sent %0d words...", i);
        end
        $display("  -> IMEM Load Complete!");

        //-----------------------------------------------------
        // PHASE 2: CORE EXECUTION
        //-----------------------------------------------------
        $display("\n[PHASE 2] Waiting for Core Execution...");
        // At this point, the HostController enters RUN state, executes, and 
        // will automatically transition to DUMP state and begin pulling the uart_tx line low.
        
        //-----------------------------------------------------
        // PHASE 3: DUMP DATA MEMORY
        //-----------------------------------------------------
        $display("\n[PHASE 3] Receiving Data Memory Dump...");
        for (i = 0; i < DMEM_WORDS; i = i + 1) begin
            receive_uart_word(captured_word);
            
            // We only print mismatches, or the first 32 words since you provided 32
            if (captured_word !== expected_dmem[i]) begin
                $display("  [FAIL] DMEM[%0d]: Expected %h, Got %h", i, expected_dmem[i], captured_word);
                errors = errors + 1;
            end else if (i < 32) begin
                $display("  [PASS] DMEM[%0d]: %h", i, captured_word);
            end
        end

        //-----------------------------------------------------
        // PHASE 4: DUMP REGISTER FILE
        //-----------------------------------------------------
        $display("\n[PHASE 4] Receiving Register File Dump...");
        for (i = 0; i < REG_WORDS; i = i + 1) begin
            receive_uart_word(captured_word);
            
            if (captured_word !== expected_reg[i]) begin
                $display("  [FAIL] REG[%0d]:  Expected %h, Got %h", i, expected_reg[i], captured_word);
                errors = errors + 1;
            end else begin
                $display("  [PASS] REG[%0d]:  %h", i, captured_word);
            end
        end

        //-----------------------------------------------------
        // FINAL VERDICT
        //-----------------------------------------------------
        #(CLK_PERIOD * 100);
        $display("\n=================================================");
        if (errors == 0) begin
            $display(" E2E SIMULATION COMPLETE: SUCCESS!");
        end else begin
            $display(" E2E SIMULATION COMPLETE: FAILED with %0d errors.", errors);
        end
        $display("=================================================");
        $finish;
    end

endmodule