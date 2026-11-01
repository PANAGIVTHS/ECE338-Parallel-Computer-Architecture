`timescale 1ns/1ps
module tb_ecall
    import gpu_pkg::*;
    import ControlPkg::*;
    import MemorySubsystemPkg::*;
#(parameter int NUM_CORES = 4) ();
    logic clk = 0, rst_n = 0;
    always #5 clk = ~clk;
    logic req_valid = 0, req_ready, req_write = 0;
    word_t req_addr = 0, req_wdata = 0, rsp_rdata;
    logic rsp_valid, idle, running, irq;
    rsp_status_t rsp_status;
    GPGPU #(.SP_PER_SM(NUM_CORES), .MEMORY_INIT(""),
        .INTERFACE_VERSION(1), .CLOCK_KHZ(100000), .BUILD_HASH(0),
        .BUILD_DIRTY(0), .DDR_ENABLE(0)) dut (
        .clk(clk), .rst_n(rst_n), .o_core_idle(idle), .o_core_running(running),
        .i_req_valid(req_valid), .o_req_ready(req_ready), .i_req_write(req_write),
        .i_req_addr(req_addr), .i_req_wdata(req_wdata), .i_req_wstrb(4'hf),
        .o_rsp_valid(rsp_valid), .i_rsp_ready(1'b1), .o_rsp_rdata(rsp_rdata),
        .o_rsp_status(rsp_status), .o_irq(irq));

    wire [31:0] regs [NUM_CORES][32];
    for (genvar c = 0; c < NUM_CORES; c++) begin : probes
        for (genvar r = 0; r < 32; r++) begin : reg_probes
            assign regs[c][r] = dut.smx.cores[c].core.regfile.written[r]
                ? dut.smx.cores[c].core.regfile.ram[r] : reg_reset_value(r,c);
        end
    end
    integer passed = 0;
    integer alu_forward = 0, wb_forward = 0, load_hazard = 0;
    integer stalled_exit = 0, stalled_redirect = 0, drain_cycles = 0;
    // Observe real pipeline use, not only final-state coincidences.
    always @(negedge clk) if (rst_n && running) begin
        if (dut.smx.idex.is_ecall) begin
            if (dut.smx.cores[0].core.forward_alu_a == pipeline_pkg::EXALU_MEMALU_DEP) alu_forward++;
            if (dut.smx.cores[0].core.forward_alu_a == pipeline_pkg::MEMWB_EXALU_DEP) wb_forward++;
            if (dut.smx.stall) stalled_exit++;
        end
        if (dut.smx.decoded.is_ecall && dut.smx.sm_ex_is_load && dut.smx.data_hazard) load_hazard++;
        if (dut.smx.stall && dut.smx.sp_feedback[0].branch_taken) stalled_redirect++;
        if (dut.smx.warp_state == 2'd1 /* WARP_DRAINING */) drain_cycles++;
        if (dut.core_complete) begin
            if ((|dut.smx.pipeline_busy) || dut.smx.o_imem_ren || !dut.memory_quiet)
                $fatal(1,"Completion before pipeline/memory drained");
        end
        if (dut.smx.warp_state != 2'd0 /* WARP_RUNNING */ && dut.smx.o_imem_ren)
            $fatal(1,"Fetch continued after warp exit");
    end

    function automatic word_t addi(int rd, int rs1, int imm);
        return {12'(imm),5'(rs1),3'b000,5'(rd),7'h13};
    endfunction
    function automatic word_t sw(int rs2, int rs1, int imm);
        return {7'(imm >> 5),5'(rs2),5'(rs1),3'b010,5'(imm),7'h23};
    endfunction
    function automatic word_t lw(int rd, int rs1, int imm);
        return {12'(imm),5'(rs1),3'b010,5'(rd),7'h03};
    endfunction
    function automatic word_t mul(int rd, int rs1, int rs2);
        return {7'h01,5'(rs2),5'(rs1),3'b000,5'(rd),7'h33};
    endfunction
    function automatic word_t jal(int rd, int off);
        return {1'(off >> 20),10'(off >> 1),1'(off >> 11),8'(off >> 12),5'(rd),7'h6f};
    endfunction
    localparam word_t ECALL = 32'h00000073, RET = 32'h00008067;

    task automatic access(input bit wr, input word_t addr, input word_t data, output word_t result);
        int timeout;
        @(negedge clk);
        req_valid = 1; req_write = wr; req_addr = addr; req_wdata = data;
        timeout = 0;
        do begin
            @(posedge clk); timeout++;
            if (timeout > 2000) $fatal(1,"Host request timeout at %h",addr);
        end while (!req_ready);
        @(negedge clk); req_valid = 0;
        timeout = 0;
        while (!rsp_valid) begin
            @(negedge clk); timeout++;
            if (timeout > 2000) $fatal(1,"Host response timeout at %h",addr);
        end
        if (rsp_status != RSP_OK) $fatal(1,"Host status %d at %h",rsp_status,addr);
        result = rsp_rdata;
        @(negedge clk);
    endtask
    task automatic write_word(input word_t addr, input word_t data);
        word_t unused;
        access(1,addr,data,unused);
    endtask
    task automatic expect_word(input word_t addr, input word_t expected);
        word_t actual;
        access(0,addr,0,actual);
        if (actual !== expected) $fatal(1,"At %h expected %h got %h",addr,expected,actual);
    endtask
    task automatic expect_reg(input int r, input word_t expected);
        for (int c=0; c<NUM_CORES; c++)
            if (regs[c][r] !== expected) $fatal(1,"Lane %d x%0d expected %h got %h",c,r,expected,regs[c][r]);
    endtask
    task automatic load_start(input word_t kernel[$]);
        if (!idle) $fatal(1,"Not idle before launch");
        write_word(REG_IRQ_STATUS,1);
        foreach (kernel[k]) write_word(IMEM_BASE + 32'(k)*4,kernel[k]);
        write_word(REG_IRQ_ENABLE,1);
        write_word(REG_CONTROL,CONTROL_START_MASK);
    endtask
    task automatic finish_run(input string name);
        int cycles;
        cycles=0;
        while (!irq && cycles<4000) begin @(negedge clk); cycles++; end
        if (!irq) $fatal(1,"%s timed out",name);
        expect_word(REG_STATUS,STATUS_IDLE_MASK);
        expect_word(REG_IRQ_STATUS,1);
        write_word(REG_IRQ_STATUS,1);
        if (irq) $fatal(1,"IRQ did not clear");
        passed++;
        $display("PASS %s",name);
    endtask
    task automatic reset_device;
        @(negedge clk); rst_n=0;
        repeat (4) @(negedge clk);
        rst_n=1;
        repeat (4) @(negedge clk);
    endtask

    word_t kernel[$];
    word_t c_image[IMEM_ENTRIES];
    string c_image_path;
    initial begin
        reset_device();
        // Exact full-word decode; malformed SYSTEM/EBREAK cannot request exit
        // or write a register. a7 is ordinary caller-saved storage until ECALL.
        kernel='{32'h00100073,32'h00001073,32'h000000f3,addi(17,0,6),
            addi(9,17,1),addi(17,0,0),ECALL,addi(9,0,999),sw(9,0,0)};
        load_start(kernel); finish_run("exact ECALL decode and younger register discard");
        expect_reg(9,7); expect_reg(1,0);

        for (int gap=0; gap<4; gap++) begin
            kernel='{addi(17,0,8),addi(10,0,321),addi(17,0,0)};
            repeat(gap) kernel.push_back(32'h00000013);
            kernel.push_back(ECALL); kernel.push_back(addi(9,0,999));
            kernel.push_back(sw(9,0,0));
            load_start(kernel); finish_run($sformatf("ALU selector zero gap %0d",gap));
            expect_reg(9,0); expect_reg(10,321); expect_reg(17,0);
        end
        for (int gap=0; gap<3; gap++) begin
            kernel='{addi(17,0,7)};
            repeat(gap) kernel.push_back(32'h00000013);
            kernel.push_back(ECALL); kernel.push_back(addi(9,0,19));
            kernel.push_back(addi(17,0,0)); kernel.push_back(ECALL);
            load_start(kernel); finish_run($sformatf("unsupported forwarded selector gap %0d",gap));
            expect_reg(9,19);
        end
        // A lane-0 zero selector is insufficient when any other lane is nonzero.
        kernel='{addi(17,31,0),ECALL,addi(9,0,23),addi(17,0,0),ECALL,addi(9,0,999)};
        if (NUM_CORES>1) begin
            load_start(kernel); finish_run("mixed lane services do not terminate"); expect_reg(9,23);
        end
        for (int service=0; service<2; service++) begin
            write_word(ControlPkg::DMEM_BASE,32'(service));
            kernel='{addi(17,0,1-service),lw(17,0,0),ECALL,addi(9,0,29),addi(17,0,0),ECALL};
            load_start(kernel); finish_run($sformatf("load selector %0d",service));
            expect_reg(9,service==0 ? 0 : 29);
        end
        for (int service=0; service<2; service++) begin
            kernel='{addi(17,0,1-service),addi(5,0,service),mul(17,5,5),ECALL,
                addi(9,0,31),addi(17,0,0),ECALL};
            load_start(kernel); finish_run($sformatf("multiply selector %0d",service));
            expect_reg(9,service==0 ? 0 : 31);
        end
        // All lanes contend for the real BRAM backend. Completion must follow
        // every store response, and no younger poison store may be submitted.
        for (int c=0;c<NUM_CORES;c++) write_word(ControlPkg::DMEM_BASE+32'(c)*4,0);
        kernel='{32'h002f9293,addi(6,0,42),addi(17,0,0),sw(6,5,0),ECALL,sw(0,5,0),addi(9,0,999)};
        load_start(kernel); finish_run("older lane stores drain, younger stores discarded");
        for (int c=0;c<NUM_CORES;c++) expect_word(ControlPkg::DMEM_BASE+32'(c)*4,42);
        expect_reg(9,0);

        // The redirect waits behind an older store while the decoded ECALL
        // is wrong-path. Flushing must win when that redirect actually executes.
        kernel='{addi(17,0,0),sw(0,0,0),jal(0,8),ECALL,addi(9,0,37),ECALL,addi(9,0,999)};
        load_start(kernel); finish_run("wrong-path ECALL behind stalled redirect"); expect_reg(9,37);

        // Nested standard returns, including a subroutine located after exit.
        kernel='{jal(1,20),addi(9,0,41),addi(17,0,0),ECALL,addi(9,0,999),
            addi(6,1,0),jal(1,12),addi(1,6,0),RET,addi(10,0,43),RET};
        load_start(kernel); finish_run("nested JAL/RET remains ordinary control flow");
        expect_reg(9,41); expect_reg(10,43);

        // An unsupported-only program must remain running until host STOP.
        kernel='{addi(17,0,1),ECALL,jal(0,0)};
        load_start(kernel); repeat (40) @(negedge clk);
        if (!running || irq) $fatal(1,"Unsupported service silently completed");
        write_word(REG_CONTROL,CONTROL_STOP_MASK);
        repeat (10) @(negedge clk);
        expect_word(REG_STATUS,STATUS_IDLE_MASK|STATUS_STOPPED_MASK);
        write_word(REG_STATUS,STATUS_STOPPED_MASK); write_word(REG_IRQ_STATUS,1);
        passed++; $display("PASS unsupported-only program remains running");

        // Freeze after acceptance: pending exit cannot vanish or complete while
        // older writeback is frozen. Reset must discard the pending request.
        kernel='{addi(17,0,0),ECALL,addi(9,0,999)};
        load_start(kernel);
        wait(dut.smx.warp_state == 2'd1 /* WARP_DRAINING */);
        @(negedge clk); force dut.smx.i_enable=1'b0;
        repeat(4) begin
            @(negedge clk);
            if (!dut.smx.stall || dut.core_complete || dut.smx.warp_state != 2'd1 /* WARP_DRAINING */)
                $fatal(1,"Pending exit changed during freeze");
        end
        release dut.smx.i_enable;
        finish_run("pending exit survives pipeline freeze"); expect_reg(9,0);
        load_start(kernel);
        wait(dut.smx.warp_state == 2'd1 /* WARP_DRAINING */);
        @(negedge clk); force dut.smx.i_enable=1'b0;
        reset_device();
        if (irq || !idle || dut.core_complete) $fatal(1,"Pending exit survived reset");
        release dut.smx.i_enable;
        load_start(kernel); finish_run("reset pending exit and relaunch"); expect_reg(9,0);

        if (!$value$plusargs("C_IMAGE=%s",c_image_path)) $fatal(1,"Missing C_IMAGE");
        $readmemh(c_image_path,c_image);
        kernel.delete();
        for(int i=0;i<IMEM_ENTRIES;i++) kernel.push_back(c_image[i]);
        load_start(kernel); finish_run("compiled C kernel and nested ILP32 returns");
        for (int c=0;c<NUM_CORES;c++) expect_word(ControlPkg::DMEM_BASE+32'(c)*4,32'(c)+105);
        expect_reg(17,0);
        if (alu_forward==0 || wb_forward==0 || load_hazard==0 || stalled_exit==0 || stalled_redirect==0 || drain_cycles==0)
            $fatal(1,"Missing coverage ALU=%d WB=%d load=%d stalled_exit=%d stalled_redirect=%d drain=%d",
                alu_forward,wb_forward,load_hazard,stalled_exit,stalled_redirect,drain_cycles);
        $display("ECALL PASS cases=%0d cores=%0d ALU=%0d WB=%0d load=%0d stalled_exit=%0d stalled_redirect=%0d drain=%0d",
            passed,NUM_CORES,alu_forward,wb_forward,load_hazard,stalled_exit,stalled_redirect,drain_cycles);
        $finish;
    end
    initial begin #10000000; $fatal(1,"Global ECALL test timeout"); end
endmodule
