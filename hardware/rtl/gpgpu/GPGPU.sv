`include "constants.svh"

module GPGPU #(
    parameter SP_PER_SM = 32,
    parameter MEMORY_INIT = "empty.mem"
) (
    input wire clk,
    input wire rst_n,

    output wire o_core_idle,
    output wire o_core_running,

    // Request signals
    input wire i_req_valid,
    output wire o_req_ready,
    input wire i_req_write,
    input wire [31:0] i_req_addr,
    input wire [31:0] i_req_wdata,
    input wire [3:0] i_req_wstrb,

    // Response signals
    output wire o_rsp_valid,
    input wire i_rsp_ready,
    output wire [31:0] o_rsp_rdata,
    output wire [2:0] o_rsp_status,

    output wire o_irq
);
    // tdb was here...

    // Control for the core
    wire [1:0] core_state;
    wire core_complete, complete_pulse, stopped;
    wire control_start, control_stop, clear_stopped;
    wire core_reset = core_state == `CORE_RESET;
    assign o_core_idle = core_state == `CORE_IDLE;
    assign o_core_running = core_state == `CORE_RUNNING;

    // CSR access description/commit. Register actions go directly to State.
    wire csr_write_fire;
    wire [31:0] csr_rdata;
    wire [2:0] csr_status;

    // Host memory path bypasses the CSR bank.
    MemoryInterface #(.ADDR_WIDTH(`IMEM_AW)) host_imem ();
    MemoryInterface #(.ADDR_WIDTH(`DMEM_AW)) host_dmem ();

    // SMX memory signals
    wire [`DMEM_AW-1:0] core_dmem_addr_a, core_dmem_addr_b;
    wire [`IMEM_AW-1:0] core_imem_addr;
    wire [31:0] core_dmem_wdata_a, core_dmem_wdata_b;
    wire core_imem_ren, core_dmem_ren_a, core_dmem_ren_b, core_dmem_wen_a, core_dmem_wen_b;

    assign dmem_if_a.addr = o_core_running ? core_dmem_addr_a : host_dmem.addr;
    assign dmem_if_a.wdata = o_core_running ? core_dmem_wdata_a : host_dmem.wdata;
    assign dmem_if_a.ren = o_core_running ? core_dmem_ren_a : host_dmem.ren;
    assign dmem_if_a.wen = o_core_running ? core_dmem_wen_a : host_dmem.wen;
    assign host_dmem.rdata = dmem_if_a.rdata;

    assign dmem_if_b.addr = core_dmem_addr_b;
    assign dmem_if_b.wdata = core_dmem_wdata_b;
    assign dmem_if_b.ren = o_core_running ? core_dmem_ren_b : 1'b0;
    assign dmem_if_b.wen = o_core_running ? core_dmem_wen_b : 1'b0;

    assign imem_if.addr = o_core_running ? core_imem_addr : host_imem.addr;
    assign imem_if.wdata = host_imem.wdata;
    assign imem_if.ren = o_core_running ? core_imem_ren : host_imem.ren;
    assign imem_if.wen = o_core_running ? 1'b0 : host_imem.wen;
    assign host_imem.rdata = imem_if.rdata;

    MMIOController mmio (
        .clk(clk), .rst_n(rst_n),
        .i_req_valid(i_req_valid), .o_req_ready(o_req_ready),
        .i_req_write(i_req_write), .i_req_addr(i_req_addr),
        .i_req_wdata(i_req_wdata), .i_req_wstrb(i_req_wstrb),
        .o_rsp_valid(o_rsp_valid), .i_rsp_ready(i_rsp_ready),
        .o_rsp_rdata(o_rsp_rdata), .o_rsp_status(o_rsp_status),
        .i_idle(o_core_idle), .imem(host_imem), .dmem(host_dmem),
        .o_csr_write_fire(csr_write_fire),
        .i_csr_rdata(csr_rdata), .i_csr_status(csr_status)
    );

    CSRBank #(.SP_PER_SM(SP_PER_SM)) regs (
        .clk(clk), .rst_n(rst_n),
        .i_write(i_req_write), .i_addr(i_req_addr), .i_wdata(i_req_wdata),
        .i_byte_en(i_req_wstrb), .i_write_fire(csr_write_fire),
        .o_rdata(csr_rdata), .o_status(csr_status),
        .i_idle(o_core_idle), .i_running(o_core_running), .i_stopped(stopped),
        .i_complete_pulse(complete_pulse),
        .o_start(control_start), .o_stop(control_stop),
        .o_clear_stopped(clear_stopped), .o_irq(o_irq)
    );

    ExecutionController state (
        .clk(clk), .rst_n(rst_n),
        .i_start(control_start), .i_stop(control_stop),
        .i_clear_stopped(clear_stopped), .i_core_complete(core_complete),
        .o_core_state(core_state), .o_stopped(stopped), .o_complete_pulse(complete_pulse)
    );

    StreamingMultiprocessor #(
        .NUM_CORES(SP_PER_SM)
    ) smx (
        .clk(clk),
        .rst(rst_n && !core_reset),
        .i_enable(o_core_running),
        .i_ifid_instruction(imem_if.rdata),
        .o_imem_addr(core_imem_addr),
        .o_imem_ren(core_imem_ren),

        .i_dmem_rdata_a(dmem_if_a.rdata),
        .o_dmem_addr_a(core_dmem_addr_a),
        .o_dmem_ren_a(core_dmem_ren_a),
        .o_dmem_wen_a(core_dmem_wen_a),
        .o_dmem_wdata_a(core_dmem_wdata_a),

        .i_dmem_rdata_b(dmem_if_b.rdata),
        .o_dmem_addr_b(core_dmem_addr_b),
        .o_dmem_ren_b(core_dmem_ren_b),
        .o_dmem_wen_b(core_dmem_wen_b),
        .o_dmem_wdata_b(core_dmem_wdata_b),

        .o_kernel_complete(core_complete)
    );

    MemoryInterface #(
        .ADDR_WIDTH($clog2(`IMEM_ENTRIES))
    ) imem_if ();

    (* dont_touch = `DEBUG *)
    MemorySinglePort #(
        .DEPTH(`IMEM_ENTRIES),
        .INIT_FILE(MEMORY_INIT)
    ) instructionMemory (
        .clk(clk),
        .memory(imem_if.slave)
    );

    MemoryInterface #(
        .ADDR_WIDTH($clog2(`DMEM_ENTRIES))
    ) dmem_if_a ();

    MemoryInterface #(
        .ADDR_WIDTH($clog2(`DMEM_ENTRIES))
    ) dmem_if_b ();

    (* dont_touch = `DEBUG *)
    MemoryDualPort #(
        .DEPTH(`DMEM_ENTRIES),
        .INIT_FILE(MEMORY_INIT)
    ) dataMemory (
        .clk(clk),
        .memory_a(dmem_if_a.slave),
        .memory_b(dmem_if_b.slave)
    );

endmodule
