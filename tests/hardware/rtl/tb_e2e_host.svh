// Shared harness for the AXI4-Lite end-to-end benches, included inside the
// bench module. The bench declares the parameters NUM_CORES,
// INTERFACE_VERSION, CLOCK_KHZ, BUILD_HASH, BUILD_DIRTY, DDR_ENABLE and
// AXI_SLAVE_LATENCY_MIN/MAX, AXI_SLAVE_READY_PCT, AXI_SLAVE_VALID_PCT,
// AXI_SLAVE_SEED, imports ControlPkg and gpu_pkg, and calls host_init() first.
//
// Provides: the gpgpu_axi DUT (UUT) with the AXI4SlaveMemory DDR model
// (ddr_mem) on its AXI4 master, the clock, the AXI4-Lite host tasks, the
// RISC-V encoders and the kernel/fault helpers.

// Every run setting is a required plusarg (supplied by the runner from the
// config file); a missing one is fatal.
`define REQUIRE_PLUSARG(fmt, var) \
    if (!$value$plusargs(fmt, var)) $fatal(1, "[ERROR] Missing required plusarg +%0s", fmt);

    // AXI response codes
    localparam logic [1:0] AXI_OKAY = 2'b00;
    localparam logic [1:0] AXI_SLVERR = 2'b10;
    localparam logic [1:0] AXI_DECERR = 2'b11;

    reg clk_in;
    reg aresetn;

    // AXI4-Lite master signals
    reg [31:0] awaddr;
    reg awvalid;
    wire awready;
    reg [31:0] wdata;
    reg [3:0] wstrb;
    reg wvalid;
    wire wready;
    wire [1:0] bresp;
    wire bvalid;
    reg bready;
    reg [31:0] araddr;
    reg arvalid;
    wire arready;
    wire [31:0] rdata;
    wire [1:0] rresp;
    wire rvalid;
    reg rready;

    wire irq;
    wire o_core_idle;
    wire o_core_running;

    // Mismatches found by the expect_* checks
    integer csr_errors;

    // Run settings (plusargs)
    real clock_period_ns;
    integer reset_cycles;
    integer test_timeout_cycles;
    integer axi_timeout_cycles;
    reg [31:0] ret_instr;
    bit settings_ready = 1'b0;

    // ============================================================
    // DUT and DDR model
    // ============================================================

    AXI4FullInterface ddr_axi ();

    gpgpu_axi #(
        .SP_PER_SM(NUM_CORES),
        .INTERFACE_VERSION(INTERFACE_VERSION),
        .CLOCK_KHZ(CLOCK_KHZ),
        .BUILD_HASH(BUILD_HASH),
        .BUILD_DIRTY(BUILD_DIRTY),
        .DDR_ENABLE(DDR_ENABLE)
    ) UUT (
        .irq(irq),
        .o_core_idle(o_core_idle),
        .o_core_running(o_core_running),

        .aclk(clk_in),
        .aresetn(aresetn),
        .s00_axi_awaddr(awaddr),
        .s00_axi_awprot(3'b000),
        .s00_axi_awvalid(awvalid),
        .s00_axi_awready(awready),
        .s00_axi_wdata(wdata),
        .s00_axi_wstrb(wstrb),
        .s00_axi_wvalid(wvalid),
        .s00_axi_wready(wready),
        .s00_axi_bresp(bresp),
        .s00_axi_bvalid(bvalid),
        .s00_axi_bready(bready),
        .s00_axi_araddr(araddr),
        .s00_axi_arprot(3'b000),
        .s00_axi_arvalid(arvalid),
        .s00_axi_arready(arready),
        .s00_axi_rdata(rdata),
        .s00_axi_rresp(rresp),
        .s00_axi_rvalid(rvalid),
        .s00_axi_rready(rready),

        `AXI4_SLAVE_CONNECT(m00_axi, ddr_axi)
    );

    AXI4SlaveMemory #(
        .LATENCY_MIN(AXI_SLAVE_LATENCY_MIN),
        .LATENCY_MAX(AXI_SLAVE_LATENCY_MAX),
        .READY_PCT(AXI_SLAVE_READY_PCT),
        .VALID_PCT(AXI_SLAVE_VALID_PCT),
        .SEED(AXI_SLAVE_SEED)
    ) ddr_mem (
        .clk(clk_in),
        .rst_n(aresetn),
        .axi(ddr_axi)
    );

    initial begin
        wait (settings_ready);
        forever #(clock_period_ns / 2.0) clk_in = ~clk_in;
    end

    // Idle bus, the shared run settings, then the clock starts.
    task automatic host_init;
        clk_in = 1'b0;
        aresetn = 1'b0;

        awaddr = '0; awvalid = 1'b0;
        wdata = '0; wstrb = '0; wvalid = 1'b0;
        bready = 1'b0;
        araddr = '0; arvalid = 1'b0;
        rready = 1'b0;

        `REQUIRE_PLUSARG("CLOCK_PERIOD_NS=%f", clock_period_ns)
        `REQUIRE_PLUSARG("RESET_CYCLES=%d", reset_cycles)
        `REQUIRE_PLUSARG("TEST_TIMEOUT_CYCLES=%d", test_timeout_cycles)
        `REQUIRE_PLUSARG("AXI_TIMEOUT_CYCLES=%d", axi_timeout_cycles)
        `REQUIRE_PLUSARG("RET_INSTR=%h", ret_instr)
        settings_ready = 1'b1;
    endtask

    // ============================================================
    // AXI4-Lite master
    // ============================================================
    // Inputs are driven on the falling edge. READY/VALID sampled at the
    // falling edge are stable up to the next rising edge, where the
    // handshake completes.

    task automatic axi_write(
        input [31:0] addr,
        input [31:0] data,
        input [3:0] strb,
        output [1:0] response
    );
        integer timeout;
        reg aw_done, w_done;
        begin
            @(negedge clk_in);
            awaddr = addr; awvalid = 1'b1;
            wdata = data; wstrb = strb; wvalid = 1'b1;
            aw_done = 1'b0; w_done = 1'b0;
            timeout = 0;

            // Address and data channels complete independently.
            while (!(aw_done && w_done)) begin
                if (timeout >= axi_timeout_cycles)
                    $fatal(1, "[ERROR] AXI write timeout (AW/W) addr=%h", addr);
                if (awvalid && awready) aw_done = 1'b1;
                if (wvalid && wready) w_done = 1'b1;
                @(negedge clk_in);
                if (aw_done) awvalid = 1'b0;
                if (w_done) wvalid = 1'b0;
                timeout = timeout + 1;
            end

            bready = 1'b1;
            timeout = 0;
            while (!bvalid) begin
                if (timeout >= axi_timeout_cycles)
                    $fatal(1, "[ERROR] AXI write timeout (B) addr=%h", addr);
                @(negedge clk_in);
                timeout = timeout + 1;
            end
            response = bresp;
            @(negedge clk_in);
            bready = 1'b0;
        end
    endtask

    task automatic axi_read(
        input [31:0] addr,
        output [31:0] data,
        output [1:0] response
    );
        integer timeout;
        begin
            @(negedge clk_in);
            araddr = addr; arvalid = 1'b1;
            timeout = 0;

            while (!arready) begin
                if (timeout >= axi_timeout_cycles)
                    $fatal(1, "[ERROR] AXI read timeout (AR) addr=%h", addr);
                @(negedge clk_in);
                timeout = timeout + 1;
            end
            @(negedge clk_in);
            arvalid = 1'b0;

            rready = 1'b1;
            timeout = 0;
            while (!rvalid) begin
                if (timeout >= axi_timeout_cycles)
                    $fatal(1, "[ERROR] AXI read timeout (R) addr=%h", addr);
                @(negedge clk_in);
                timeout = timeout + 1;
            end
            data = rdata;
            response = rresp;
            @(negedge clk_in);
            rready = 1'b0;
        end
    endtask

    // ============================================================
    // Device access helpers (expect OKAY)
    // ============================================================

    task automatic write_word(input [31:0] addr, input [31:0] data);
        reg [1:0] response;
        begin
            axi_write(addr, data, 4'b1111, response);
            if (response !== AXI_OKAY)
                $fatal(1, "[ERROR] Write addr=%h data=%h failed with resp=%b", addr, data, response);
        end
    endtask

    task automatic read_word(input [31:0] addr, output [31:0] data);
        reg [1:0] response;
        begin
            axi_read(addr, data, response);
            if (response !== AXI_OKAY)
                $fatal(1, "[ERROR] Read addr=%h failed with resp=%b", addr, response);
        end
    endtask

    task automatic write_imem(input integer index, input [31:0] data);
        write_word(IMEM_BASE + 32'(index) * 4, data);
    endtask

    task automatic read_imem(input integer index, output [31:0] data);
        read_word(IMEM_BASE + 32'(index) * 4, data);
    endtask

    task automatic write_dmem(input integer index, input [31:0] data);
        write_word(ControlPkg::DMEM_BASE + 32'(index) * 4, data);
    endtask

    task automatic read_dmem(input integer index, output [31:0] data);
        read_word(ControlPkg::DMEM_BASE + 32'(index) * 4, data);
    endtask

    // Read a CSR and compare against an expected value; counts mismatches.
    task automatic expect_csr(input [31:0] addr, input [31:0] expected, input string name);
        reg [31:0] data;
        begin
            read_word(addr, data);
            if (data !== expected) begin
                $display("  [ERROR] %0s (0x%0h): Expected %h, Found %h", name, addr, expected, data);
                csr_errors = csr_errors + 1;
            end
        end
    endtask

    task automatic expect_write_resp(input [31:0] addr, input [31:0] data, input [1:0] expected);
        reg [1:0] response;
        begin
            axi_write(addr, data, 4'b1111, response);
            if (response !== expected) begin
                $display("  [ERROR] Write addr=%h: Expected resp %b, Found %b", addr, expected, response);
                csr_errors = csr_errors + 1;
            end
        end
    endtask

    task automatic expect_read_resp(input [31:0] addr, input [1:0] expected);
        reg [31:0] data;
        reg [1:0] response;
        begin
            axi_read(addr, data, response);
            if (response !== expected) begin
                $display("  [ERROR] Read addr=%h: Expected resp %b, Found %b", addr, expected, response);
                csr_errors = csr_errors + 1;
            end
        end
    endtask

    // ============================================================
    // Performance counters (PerfPkg), read over AXI4-Lite
    // ============================================================
    // Sized by the register map's slots, so the counter enums index them
    longint unsigned perf_global [PERF_GLOBAL_SLOTS];
    longint unsigned perf_warp [warp_pkg::WARPS_PER_SM][PERF_WARP_SLOTS];

    task automatic read_perf(input [31:0] addr, output longint unsigned value);
        reg [31:0] lo, hi;
        begin
            read_word(addr, lo);
            read_word(addr + PERF_HI_OFFSET, hi);
            value = {hi, lo};
        end
    endtask

    task automatic read_all_perf;
        for (int unsigned c = 0; c < PerfPkg::PERF_GLOBAL_COUNT; c++)
            read_perf(PERF_GLOBAL_BASE + PERF_COUNTER_BYTES * c, perf_global[c]);
        for (int unsigned w = 0; w < warp_pkg::WARPS_PER_SM; w++)
            for (int unsigned l = 0; l < PerfPkg::PERF_WARP_LEAF_COUNT; l++)
                read_perf(PERF_WARP_BASE + PERF_WARP_STRIDE * w + PERF_COUNTER_BYTES * l, perf_warp[w][l]);
    endtask

    function automatic longint unsigned perf_g(input PerfPkg::perf_global_t c);
        return perf_global[c];
    endfunction

    // The consistency rules of docs/perf-counters-spec.md §6 that hold for
    // every run, printing the breakdown; mismatches count as CSR errors.
    task automatic check_perf(input string name);
        longint unsigned kernel, leaf_sum, ring_full_leaves;
        PerfPkg::perf_warp_leaf_t leaf;
        begin
            read_all_perf();
            kernel = perf_g(PerfPkg::PERF_KERNEL_CYCLES);
            ring_full_leaves = 0;
            for (int unsigned w = 0; w < warp_pkg::WARPS_PER_SM; w++) begin
                leaf_sum = 0;
                $write("  [PERF] %0s: %0d cycles (reset %0d, drain %0d), warp %0d:", name, kernel,
                       perf_g(PerfPkg::PERF_RUN_RESET), perf_g(PerfPkg::PERF_RUN_DRAIN), w);
                for (int unsigned l = 0; l < PerfPkg::PERF_WARP_LEAF_COUNT; l++) begin
                    leaf = PerfPkg::perf_warp_leaf_t'(l);
                    leaf_sum += perf_warp[w][l];
                    if (perf_warp[w][l] != 0)
                        $write(" %s=%0d", leaf.name(), perf_warp[w][l]);
                end
                $write("\n");
                ring_full_leaves += perf_warp[w][PerfPkg::PERF_WARP_ST_RING_FULL];
                if (perf_g(PerfPkg::PERF_RUN_RESET) + perf_g(PerfPkg::PERF_RUN_DRAIN) + leaf_sum != kernel) begin
                    $display("  [ERROR] %0s: reset + drain + warp %0d leaves = %0d, not KERNEL_CYCLES %0d", name, w,
                             perf_g(PerfPkg::PERF_RUN_RESET) + perf_g(PerfPkg::PERF_RUN_DRAIN) + leaf_sum, kernel);
                    csr_errors = csr_errors + 1;
                end
            end
            $display("  [PERF] %0s: AW transfer %0d blocked %0d idle %0d; W transfer %0d blocked %0d wait_aw %0d idle %0d; ring full %0d",
                     name, perf_g(PerfPkg::PERF_AW_TRANSFER), perf_g(PerfPkg::PERF_AW_BLOCKED), perf_g(PerfPkg::PERF_AW_IDLE),
                     perf_g(PerfPkg::PERF_W_TRANSFER), perf_g(PerfPkg::PERF_W_BLOCKED), perf_g(PerfPkg::PERF_W_WAIT_AW),
                     perf_g(PerfPkg::PERF_W_IDLE), perf_g(PerfPkg::PERF_WR_RING_FULL));
            if (perf_g(PerfPkg::PERF_AW_TRANSFER) + perf_g(PerfPkg::PERF_AW_BLOCKED) + perf_g(PerfPkg::PERF_AW_IDLE) != kernel) begin
                $display("  [ERROR] %0s: the AW partition does not sum to KERNEL_CYCLES", name);
                csr_errors = csr_errors + 1;
            end
            if (perf_g(PerfPkg::PERF_W_TRANSFER) + perf_g(PerfPkg::PERF_W_BLOCKED) + perf_g(PerfPkg::PERF_W_WAIT_AW)
                    + perf_g(PerfPkg::PERF_W_IDLE) != kernel) begin
                $display("  [ERROR] %0s: the W partition does not sum to KERNEL_CYCLES", name);
                csr_errors = csr_errors + 1;
            end
            if (ring_full_leaves > perf_g(PerfPkg::PERF_WR_RING_FULL)) begin
                $display("  [ERROR] %0s: WARP_ST_RING_FULL %0d exceeds WR_RING_FULL %0d", name,
                         ring_full_leaves, perf_g(PerfPkg::PERF_WR_RING_FULL));
                csr_errors = csr_errors + 1;
            end
            if (perf_g(PerfPkg::PERF_BRAM_BUSY) > perf_g(PerfPkg::PERF_BRAM_ACCESSES) ||
                perf_g(PerfPkg::PERF_BRAM_ACCESSES) > MemorySubsystemPkg::BRAM_PORTS * perf_g(PerfPkg::PERF_BRAM_BUSY)) begin
                $display("  [ERROR] %0s: BRAM accesses %0d outside busy cycles %0d to %0d x busy", name,
                         perf_g(PerfPkg::PERF_BRAM_ACCESSES), perf_g(PerfPkg::PERF_BRAM_BUSY), MemorySubsystemPkg::BRAM_PORTS);
                csr_errors = csr_errors + 1;
            end
        end
    endtask

    // ============================================================
    // Fault checks: short kernels built from these encoders, so the
    // addresses they use come from gpu_pkg rather than fixed encodings.
    // ============================================================
    function automatic logic [31:0] rv_add(input int rd, input int rs1, input int rs2);
        return {7'd0, 5'(rs2), 5'(rs1), 3'b000, 5'(rd), 7'b0110011};
    endfunction

    function automatic logic [31:0] rv_addi(input int rd, input int rs1, input int imm);
        return {12'(imm), 5'(rs1), 3'b000, 5'(rd), 7'b0010011};
    endfunction

    function automatic logic [31:0] rv_lui(input int rd, input logic [31:0] value);
        return {value[31:12], 5'(rd), 7'b0110111};
    endfunction

    function automatic logic [31:0] rv_lw(input int rd, input int rs1, input int imm);
        return {12'(imm), 5'(rs1), 3'b010, 5'(rd), 7'b0000011};
    endfunction

    function automatic logic [31:0] rv_sw(input int rs2, input int rs1, input int imm);
        logic [11:0] offset;
        offset = 12'(imm);
        return {offset[11:5], 5'(rs2), 5'(rs1), 3'b010, offset[4:0], 7'b0100011};
    endfunction

    function automatic logic [31:0] rv_slli(input int rd, input int rs1, input int shamt);
        return {7'd0, 5'(shamt), 5'(rs1), 3'b001, 5'(rd), 7'b0010011};
    endfunction

    // offset in bytes from this instruction
    function automatic logic [31:0] rv_bne(input int rs1, input int rs2, input int offset);
        logic [12:0] imm;
        imm = 13'(offset);
        return {imm[12], imm[10:5], 5'(rs2), 5'(rs1), 3'b001, imm[4:1], imm[11], 7'b1100011};
    endfunction

    // Lane masks and FAULT_INFO values
    function automatic logic [31:0] all_lanes();
        return 32'((64'd1 << NUM_CORES) - 1);
    endfunction

    function automatic logic [31:0] fault_kind(input MemorySubsystemPkg::mem_status_t status);
        return 32'd1 << (FAULT_KINDS_LSB + 32'(status) - 1);
    endfunction

    // Run a kernel (x31 holds the lane id) to its completion interrupt.
    task automatic run_kernel(input logic [31:0] kernel[$]);
        integer cycles;
        foreach (kernel[k])
            write_imem(k, kernel[k]);
        write_word(REG_IRQ_ENABLE, 32'd1);
        write_word(REG_CONTROL, CONTROL_START_MASK);
        cycles = 0;
        while (irq !== 1'b1 && cycles < test_timeout_cycles) begin
            @(posedge clk_in);
            cycles = cycles + 1;
        end
        if (irq !== 1'b1)
            $fatal(1, "[ERROR] Kernel reached timeout of %0d cycles without IRQ", test_timeout_cycles);
        write_word(REG_IRQ_STATUS, 32'd1);
        write_word(REG_IRQ_ENABLE, 32'd0);
        check_perf("kernel");
    endtask

    // A faulting kernel ends IDLE with FAULTED set and the fault report;
    // START is refused until the W1C, which leaves the report readable.
    task automatic expect_fault(
        input string name,
        input logic [31:0] kernel[$],
        input logic [31:0] info,
        input logic [31:0] lanes,
        input logic [31:0] pc
    );
        $display("[INFO]  Fault check: %0s", name);
        run_kernel(kernel);
        expect_csr(REG_STATUS, STATUS_IDLE_MASK | STATUS_FAULTED_MASK, {name, ": STATUS"});
        expect_csr(REG_FAULT_INFO, info, {name, ": FAULT_INFO"});
        expect_csr(REG_FAULT_LANES, lanes, {name, ": FAULT_LANES"});
        expect_csr(REG_FAULT_PC, pc, {name, ": FAULT_PC"});
        expect_write_resp(REG_CONTROL, CONTROL_START_MASK, AXI_SLVERR);   // refused while FAULTED
        write_word(REG_STATUS, STATUS_FAULTED_MASK);                        // W1C
        expect_csr(REG_STATUS, STATUS_IDLE_MASK, {name, ": STATUS after clear"});
        expect_csr(REG_FAULT_INFO, info, {name, ": FAULT_INFO after clear"});
    endtask

    task automatic reset_device;
        begin
            aresetn = 1'b0;
            repeat (reset_cycles) @(posedge clk_in);
            @(negedge clk_in);
            aresetn = 1'b1;
            repeat (5) @(posedge clk_in);
        end
    endtask

    // ============================================================
    // Directed cases (cases/test<N>): load, launch, check
    // ============================================================
    // Each case is loaded through AXI4-Lite, run to its completion IRQ, and
    // checked against the expected files of expected_generator.py: all of
    // DMEM, and for a case that uses DDR, the DDR model's contents and burst
    // count (its ddr_seed file is loaded first). Without the DDR backend such
    // a case is skipped. Ends the simulation after the last case.

    reg [31:0] expected_imem [0:IMEM_ENTRIES-1];
    reg [31:0] expected_dmem [0:DMEM_ENTRIES-1];

    function automatic bit file_exists(input string path);
        int fd;
        fd = $fopen(path, "r");
        if (fd == 0)
            return 1'b0;
        $fclose(fd);
        return 1'b1;
    endfunction

    task automatic run_cases;
        integer i;
        integer test_idx;
        integer test_end;
        bit has_test_end;
        integer fd;
        integer imem_errors;
        integer dmem_errors;
        int unsigned ddr_errors;
        integer cycle_count;
        integer program_words;
        bit found_ret;
        bit has_ddr;
        reg [31:0] captured_word;
        string test_root, case_prefix, program_name, data_name, ddr_seed_name, ddr_name, perf_name;
        string prog_file, data_file, ddr_seed_file, ddr_file, perf_file;
        string perf_key;
        longint unsigned model_instructions;

        `REQUIRE_PLUSARG("TEST_ROOT=%s", test_root)
        `REQUIRE_PLUSARG("TEST_IDX=%d", test_idx)
        `REQUIRE_PLUSARG("CASE_PREFIX=%s", case_prefix)
        `REQUIRE_PLUSARG("PROGRAM_FILE=%s", program_name)
        `REQUIRE_PLUSARG("DATA_FILE=%s", data_name)
        `REQUIRE_PLUSARG("DDR_SEED_FILE=%s", ddr_seed_name)
        `REQUIRE_PLUSARG("DDR_FILE=%s", ddr_name)
        `REQUIRE_PLUSARG("PERF_FILE=%s", perf_name)
        has_test_end = $value$plusargs("TEST_END=%d", test_end) != 0;
        $display("\n[INFO] ---> Directed cases from %0s", test_root);

        forever begin
            if (has_test_end && test_idx > test_end) begin
                $display("\n[INFO] Reached requested TEST_END=%0d. Simulation finished successfully!", test_end);
                $finish;
                // The simulator can continue this time slot after $finish.
                break;
            end

            // ----------------------------------------------------
            // Find test files
            // ----------------------------------------------------
            prog_file = $sformatf("%0s/%0s%0d/%0s", test_root, case_prefix, test_idx, program_name);
            data_file = $sformatf("%0s/%0s%0d/%0s", test_root, case_prefix, test_idx, data_name);
            ddr_seed_file = $sformatf("%0s/%0s%0d/%0s", test_root, case_prefix, test_idx, ddr_seed_name);
            ddr_file = $sformatf("%0s/%0s%0d/%0s", test_root, case_prefix, test_idx, ddr_name);
            perf_file = $sformatf("%0s/%0s%0d/%0s", test_root, case_prefix, test_idx, perf_name);

            fd = $fopen(prog_file, "r");
            if (fd == 0) begin
                if (test_idx == 1)
                    $fatal(1, "[ERROR] No tests were found");
                else
                    $display("\n[INFO] Simulation finished successfully!");

                $finish;
                // The simulator can continue this time slot after $finish.
                break;
            end
            $fclose(fd);

            $display("\n[INFO] ---> Starting test %0d...", test_idx);

            // A case that uses DDR has an expected DDR file.
            has_ddr = file_exists(ddr_file);
            if (has_ddr && DDR_ENABLE == 0) begin
                $display("[INFO]  Uses DDR: skipped without the DDR backend.");
                test_idx = test_idx + 1;
                continue;
            end

            // ----------------------------------------------------
            // Initialize expected arrays
            // ----------------------------------------------------
            for (i = 0; i < IMEM_ENTRIES; i = i + 1)
                expected_imem[i] = NOP_INSTR;

            for (i = 0; i < DMEM_ENTRIES; i = i + 1)
                expected_dmem[i] = 32'b0;

            $readmemh(prog_file, expected_imem);
            $readmemh(data_file, expected_dmem);

            // Only load up to (and including) the kernel's RET.
            program_words = IMEM_ENTRIES;
            found_ret = 0;
            for (i = 0; i < IMEM_ENTRIES; i = i + 1) begin
                if (!found_ret && expected_imem[i] == ret_instr) begin
                    program_words = i + 1;
                    found_ret = 1;
                end
            end

            if (!found_ret)
                $display("[WARNING] No RET instruction 0x%08h found in %0s. Loading full IMEM.",
                         ret_instr, prog_file);
            else
                $display("[INFO]  Program length detected: %0d words. RET at IMEM[%0d].",
                         program_words, program_words - 1);

            // ----------------------------------------------------
            // Reset (BRAM contents survive reset)
            // ----------------------------------------------------
            reset_device();
            ddr_mem.clear();
            if (file_exists(ddr_seed_file))
                ddr_mem.load_words(ddr_seed_file);

            if (o_core_idle !== 1'b1)
                $fatal(1, "[ERROR] GPGPU did not enter idle after reset");

            // ----------------------------------------------------
            // Clear DMEM, load and verify IMEM
            // ----------------------------------------------------
            $display("[INFO]  Clearing DMEM...");
            for (i = 0; i < DMEM_ENTRIES; i = i + 1)
                write_dmem(i, 32'b0);

            $display("[INFO]  Loading IMEM...");
            for (i = 0; i < program_words; i = i + 1)
                write_imem(i, expected_imem[i]);

            $display("[INFO]  Verifying IMEM...");
            imem_errors = 0;
            for (i = 0; i < program_words; i = i + 1) begin
                read_imem(i, captured_word);
                if (captured_word !== expected_imem[i]) begin
                    $display("  [ERROR] IMEM[%0d]: Expected %h, Found %h",
                             i, expected_imem[i], captured_word);
                    imem_errors = imem_errors + 1;
                end
            end

            if (imem_errors != 0)
                $fatal(1, "[ERROR] Test %0d: IMEM verification failed with %0d errors",
                       test_idx, imem_errors);

            // ----------------------------------------------------
            // Launch and wait for the completion interrupt
            // ----------------------------------------------------
            csr_errors = 0;
            write_word(REG_IRQ_ENABLE, 32'd1);

            $display("[INFO]  Starting kernel...");
            write_word(REG_CONTROL, CONTROL_START_MASK);

            cycle_count = 0;
            while (irq !== 1'b1 && cycle_count < test_timeout_cycles) begin
                @(posedge clk_in);
                cycle_count = cycle_count + 1;
            end

            if (irq !== 1'b1)
                $fatal(1, "[ERROR] Test %0d reached timeout of %0d cycles without IRQ (idle=%b running=%b)",
                       test_idx, test_timeout_cycles, o_core_idle, o_core_running);

            $display("[INFO]  Completion IRQ after %0d cycles.", cycle_count);

            // Completion leaves the device idle and not stopped.
            expect_csr(REG_STATUS, STATUS_IDLE_MASK, "STATUS");
            expect_csr(REG_IRQ_STATUS, 32'd1, "IRQ_STATUS");

            // W1C acknowledge must drop the interrupt line.
            write_word(REG_IRQ_STATUS, 32'd1);
            @(negedge clk_in);
            if (irq !== 1'b0) begin
                $display("  [ERROR] IRQ still asserted after IRQ_STATUS W1C");
                csr_errors = csr_errors + 1;
            end
            expect_csr(REG_IRQ_STATUS, 32'd0, "IRQ_STATUS");

            if (!ddr_mem.idle()) begin
                $display("  [ERROR] A DDR transaction is still open after completion");
                csr_errors = csr_errors + 1;
            end

            // ----------------------------------------------------
            // Performance counters: the rules of every run, and the
            // instructions the model executed (expected_generator.py)
            // ----------------------------------------------------
            check_perf($sformatf("test %0d", test_idx));
            fd = $fopen(perf_file, "r");
            if (fd == 0)
                $fatal(1, "[ERROR] Test %0d: no %0s (run tests:rtl:generate)", test_idx, perf_file);
            if ($fscanf(fd, "%s %d", perf_key, model_instructions) != 2 || perf_key != "instructions")
                $fatal(1, "[ERROR] %0s: expected 'instructions <count>' first", perf_file);
            $fclose(fd);
            // The instruction at RET's target issues before the controller
            // sees the completion: one more than the kernel executes, until
            // the halt instruction changes.
            for (int unsigned w = 0; w < warp_pkg::WARPS_PER_SM; w++) begin
                if (perf_warp[w][PerfPkg::PERF_WARP_ISSUED] != model_instructions + 1) begin
                    $display("  [ERROR] Warp %0d WARP_ISSUED: Expected %0d (the model's %0d + 1), Found %0d", w,
                             model_instructions + 1, model_instructions, perf_warp[w][PerfPkg::PERF_WARP_ISSUED]);
                    csr_errors = csr_errors + 1;
                end
            end

            // ----------------------------------------------------
            // Read back and verify DMEM
            // ----------------------------------------------------
            $display("[INFO]  Verifying DMEM...");
            dmem_errors = 0;
            for (i = 0; i < DMEM_ENTRIES; i = i + 1) begin
                read_dmem(i, captured_word);
                if (captured_word !== expected_dmem[i]) begin
                    $display("  [ERROR] DMEM[%0d]: Expected %h, Found %h",
                             i, expected_dmem[i], captured_word);
                    dmem_errors = dmem_errors + 1;
                end
            end

            // ----------------------------------------------------
            // Verdict
            // ----------------------------------------------------
            ddr_errors = 0;
            if (has_ddr) begin
                $display("[INFO]  Verifying DDR...");
                ddr_errors = ddr_mem.check_words(ddr_file);
            end

            if (dmem_errors == 0 && ddr_errors == 0 && csr_errors == 0) begin
                $display("  [SUCCESS] Test %0d passed in %0d cycles.", test_idx, cycle_count);
            end else begin
                $display("  [WARNING] Test %0d failed. DMEM errors: %0d, DDR errors: %0d, CSR errors: %0d",
                         test_idx, dmem_errors, ddr_errors, csr_errors);
                $fatal(1, "[ERROR] Halting simulation due to E2E GPGPU test failure.");
            end

            test_idx = test_idx + 1;
        end
    endtask
