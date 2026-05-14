`timescale 1ns / 1ps

module tb_host_transmitter();

    // 10MHz Clock, 625,000 Baud
    localparam CLK_PERIOD = 100; 
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

    wire [9:0] dmem_addr;
    wire [4:0] reg_addr;
    reg  [31:0] dummy_dmem_rdata;
    reg  [31:0] dummy_reg_rdata;

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
    // MOCK MEMORY ARRAYS (With 1-Cycle Latency!)
    //==============================================
    reg [31:0] mock_dmem [0:1023];
    reg [31:0] mock_reg  [0:31];

    // Initialize the memory with highly recognizable hex patterns
    integer i;
    initial begin
        for (i = 0; i < 1024; i = i + 1) begin
            mock_dmem[i] = 32'hDA7A_0000 + i; // e.g. DA7A0000, DA7A0001...
        end
        for (i = 0; i < 32; i = i + 1) begin
            mock_reg[i]  = 32'hBEEF_0000 + i; // e.g. BEEF0000, BEEF0001...
        end
    end

    // CRITICAL: We use a clocked always block to simulate the exact 
    // 1-clock-cycle delay of physical BRAM. This proves your pipeline works!
    always @(posedge clk) begin
        dummy_dmem_rdata <= mock_dmem[dmem_addr];
        dummy_reg_rdata  <= mock_reg[reg_addr];
    end

    //==============================================
    // UART RECEIVE TASKS (Simulates the PC receiving data)
    //==============================================
    task receive_uart_byte(output reg [7:0] rec_data);
        integer b;
        begin
            wait(uart_tx == 1'b0); // Wait for the Start Bit to drop
            #(BIT_PERIOD / 2);     // Wait half a bit to sample the center
            
            if (uart_tx !== 1'b0) $display("ERROR: Start bit not stable!");
            #(BIT_PERIOD);         // Move to the center of Bit 0

            for (b = 0; b < 8; b = b + 1) begin
                rec_data[b] = uart_tx; // Sample the data bit
                #(BIT_PERIOD);
            end
            
            if (uart_tx !== 1'b1) $display("ERROR: Stop bit missing!");
        end
    endtask

    task receive_uart_word(output reg [31:0] rec_word);
        reg [7:0] byte3, byte2, byte1, byte0;
        begin
            receive_uart_byte(byte3); // MSB
            receive_uart_byte(byte2);
            receive_uart_byte(byte1);
            receive_uart_byte(byte0); // LSB
            rec_word = {byte3, byte2, byte1, byte0};
        end
    endtask

    //==============================================
    // MAIN TEST SEQUENCE
    //==============================================
    integer w;
    reg [31:0] captured_word;

    initial begin
        $display("=================================================");
        $display(" Starting Host Controller TX Dump Test");
        $display("=================================================");

        // 1. Initialize
        clk = 0;
        rst = 0;
        core_complete = 0;
        uart_rx = 1; // Keep RX idle

        // 2. Apply Reset
        #(CLK_PERIOD * 10);
        rst = 1;
        #(CLK_PERIOD * 10);

        // 3. Bypass the LOAD state using the 'force' command
        $display("[System] Teleporting FSM to RUN state...");
        force UUT.current_state = 2'b01; // 2'b01 is your RUN state
        force UUT.uart_controller.current_state = 4'd0; // IDLE state
        #(CLK_PERIOD * 10);
        release UUT.uart_controller.current_state;
        release UUT.current_state;       // Give control back to the Verilog logic

        // 4. Trigger the Core Complete signal!
        $display("[System] Asserting core_complete to trigger DUMP...");
        core_complete = 1;
        #(CLK_PERIOD * 5);
        core_complete = 0; // Drop it, FSM should now be locked in DUMP

        // 5. Start Receiving Data Memory
        $display("\n--- Awaiting Data Memory (1024 Words) ---");
        for (w = 0; w < 1024; w = w + 1) begin
            receive_uart_word(captured_word);
            
            if (captured_word !== mock_dmem[w]) begin
                $display("  [FAIL] DMEM[%0d]: Expected %h, Got %h", w, mock_dmem[w], captured_word);
            end else if (w % 256 == 0 || w == 1023) begin
                $display("  [PASS] DMEM[%0d] = %h", w, captured_word);
            end
        end

        // 6. Start Receiving Register File
        $display("\n--- Awaiting Register File (32 Words) ---");
        for (w = 0; w < 32; w = w + 1) begin
            receive_uart_word(captured_word);
            
            if (captured_word !== mock_reg[w]) begin
                $display("  [FAIL] REG[%0d]: Expected %h, Got %h", w, mock_reg[w], captured_word);
            end else if (w == 0 || w == 31) begin
                $display("  [PASS] REG[%0d] = %h", w, captured_word);
            end
        end

        // Let the state machine settle and return to IDLE
        #(CLK_PERIOD * 50);

        $display("=================================================");
        $display(" TX Dump Simulation Complete!");
        $display("=================================================");
        $finish;
    end

    //==============================================
    // WAVEFORM DUMP
    //==============================================
    initial begin
        $dumpfile("host_tx_dump.vcd");
        $dumpvars(0, tb_host_transmitter);
    end

endmodule