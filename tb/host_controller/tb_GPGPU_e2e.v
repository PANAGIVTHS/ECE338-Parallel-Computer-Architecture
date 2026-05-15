`timescale 1ns / 1ps

module tb_GPGPU_e2e_command();

    //==================================================
    // Constants
    //==================================================
    localparam CLK_PERIOD = 10;

    localparam IMEM_WORDS = 1024;
    localparam DMEM_WORDS = 1024;
    localparam REG_WORDS  = 32;

    // Host commands
    localparam CMD_IMEM_WRITE = 3'd0;
    localparam CMD_WRITE_DONE = 3'd1;
    localparam CMD_DMEM_READ  = 3'd2;
    localparam CMD_REG_READ   = 3'd3;
    localparam CMD_READ_DONE  = 3'd4;

    //==================================================
    // DUT signals
    //==================================================
    reg clk;
    reg rst;

    wire o_loading;
    wire o_running;
    wire o_dumping;

    reg [2:0]  host_command;
    reg        host_command_valid;
    reg [31:0] host_address;
    reg [31:0] host_wdata;

    wire [31:0] host_rdata;
    wire host_busy;
    wire host_done;

    //==================================================
    // DUT
    //==================================================
    GPGPU UUT (
        .i_clk(clk),
        .i_rst(rst),

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

    //==================================================
    // Clock
    //==================================================
    always #(CLK_PERIOD / 2.0) clk = ~clk;

    //==================================================
    // Expected memories
    //==================================================
    reg [31:0] expected_imem [0:IMEM_WORDS-1];
    reg [31:0] expected_dmem [0:DMEM_WORDS-1];
    reg [31:0] expected_reg  [0:REG_WORDS-1];

    //==================================================
    // Command task
    //==================================================
    task send_command(
        input [2:0]  cmd,
        input [31:0] addr,
        input [31:0] wdata
    );
        begin
            // Wait until accelerator command interface is available
            while (host_busy) begin
                @(posedge clk);
            end

            // Present command fields
            host_command <= cmd;
            host_address <= addr;
            host_wdata   <= wdata;

            // Assert valid and KEEP IT HIGH until done
            host_command_valid <= 1'b1;

            // Wait for command completion
            while (!host_done) begin
                @(posedge clk);
            end

            // Command is complete; deassert valid
            host_command_valid <= 1'b0;

            // Wait for done to drop before next command
            while (host_done) begin
                @(posedge clk);
            end
        end
    endtask

    //==================================================
    // IMEM write helper
    //==================================================
    task write_imem(
        input [31:0] addr,
        input [31:0] instr
    );
        begin
            send_command(CMD_IMEM_WRITE, addr, instr);
        end
    endtask

    //==================================================
    // DMEM read helper
    //==================================================
    task read_dmem(
        input [31:0] addr,
        output [31:0] data
    );
        begin
            send_command(CMD_DMEM_READ, addr, 32'b0);

            // send_command returns only after done was seen,
            // so host_rdata should now be stable.
            data = host_rdata;
        end
    endtask

    //==================================================
    // REG read helper
    //==================================================
    task read_reg(
        input [31:0] addr,
        output [31:0] data
    );
        begin
            send_command(CMD_REG_READ, addr, 32'b0);

            // send_command returns only after done was seen,
            // so host_rdata should now be stable.
            data = host_rdata;
        end
    endtask

    //==================================================
    // Main test
    //==================================================
    integer i;
    integer errors;
    reg [31:0] captured_word;

    initial begin
        $display("=================================================");
        $display(" Starting Command-Based GPGPU E2E Simulation...");
        $display("=================================================");

        clk = 1'b0;
        rst = 1'b0;

        host_command       = 3'b0;
        host_command_valid = 1'b0;
        host_address       = 32'b0;
        host_wdata         = 32'b0;

        errors = 0;

        // Initialize expected arrays
        for (i = 0; i < IMEM_WORDS; i = i + 1)
            expected_imem[i] = 32'h00000013; // NOP

        expected_imem[1000] = 32'h00008067; // RET

        for (i = 0; i < DMEM_WORDS; i = i + 1)
            expected_dmem[i] = 32'b0;

        for (i = 0; i < REG_WORDS; i = i + 1)
            expected_reg[i] = 32'b0;

        // Optional file-based expected data
        $readmemh("program.mem", expected_imem);
        $readmemh("data.mem", expected_dmem);
        $readmemh("regfile.mem", expected_reg);

        // Reset
        repeat (10) @(posedge clk);
        rst <= 1'b1;
        repeat (10) @(posedge clk);

        if (!o_loading) begin
            $display("[WARN] DUT did not start in LOADING state.");
        end

        //--------------------------------------------------
        // PHASE 1: Load instruction memory
        //--------------------------------------------------
        $display("\n[PHASE 1] Writing IMEM using host commands...");

        for (i = 0; i < IMEM_WORDS; i = i + 1) begin
            write_imem(i, expected_imem[i]);

            if (i > 0 && i % 256 == 0)
                $display("  ...Wrote %0d IMEM words...", i);
        end

        $display("  -> IMEM write complete.");

        //--------------------------------------------------
        // PHASE 2: Tell core program load is complete
        //--------------------------------------------------
        $display("\n[PHASE 2] Sending WRITE_DONE command...");
        send_command(CMD_WRITE_DONE, 32'b0, 32'b0);

        //--------------------------------------------------
        // PHASE 3: Wait for execution
        //--------------------------------------------------
        $display("\n[PHASE 3] Waiting for core to enter DUMPING state...");

        wait (o_running == 1'b1);
        $display("  -> Core entered RUNNING state.");

        wait (o_dumping == 1'b1);
        $display("  -> Core entered DUMPING state.");

        //--------------------------------------------------
        // PHASE 4: Read DMEM
        //--------------------------------------------------
        $display("\n[PHASE 4] Reading DMEM using host commands...");

        for (i = 0; i < DMEM_WORDS; i = i + 1) begin
            read_dmem(i, captured_word);

            if (captured_word !== expected_dmem[i]) begin
                $display("  [FAIL] DMEM[%0d]: Expected %h, Got %h",
                         i, expected_dmem[i], captured_word);
                errors = errors + 1;
            end else if (i < 32) begin
                $display("  [PASS] DMEM[%0d]: %h", i, captured_word);
            end
        end

        //--------------------------------------------------
        // PHASE 5: Read register file
        //--------------------------------------------------
        $display("\n[PHASE 5] Reading register file using host commands...");

        for (i = 0; i < REG_WORDS; i = i + 1) begin
            read_reg(i, captured_word);

            if (captured_word !== expected_reg[i]) begin
                $display("  [FAIL] REG[%0d]: Expected %h, Got %h",
                         i, expected_reg[i], captured_word);
                errors = errors + 1;
            end else begin
                $display("  [PASS] REG[%0d]: %h", i, captured_word);
            end
        end

        //--------------------------------------------------
        // PHASE 6: Tell host controller readback is done
        //--------------------------------------------------
        $display("\n[PHASE 6] Sending READ_DONE command...");
        send_command(CMD_READ_DONE, 32'b0, 32'b0);

        wait (o_loading == 1'b1);
        $display("  -> Core returned to LOADING state.");

        //--------------------------------------------------
        // Final verdict
        //--------------------------------------------------
        repeat (10) @(posedge clk);

        $display("\n=================================================");
        if (errors == 0)
            $display(" COMMAND E2E SIMULATION COMPLETE: SUCCESS!");
        else
            $display(" COMMAND E2E SIMULATION COMPLETE: FAILED with %0d errors.", errors);
        $display("=================================================");

        $finish;
    end

endmodule