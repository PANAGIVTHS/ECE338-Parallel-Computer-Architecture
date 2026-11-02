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

        .s00_axi_aclk(clk_in),
        .s00_axi_aresetn(aresetn),
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
