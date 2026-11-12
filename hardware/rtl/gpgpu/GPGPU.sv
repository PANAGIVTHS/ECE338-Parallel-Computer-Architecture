`include "constants.svh"

module GPGPU
    import gpu_pkg::*;
    import ControlPkg::*;
    import MemorySubsystemPkg::*;
    import AXI4FullPkg::*;
    import warp_pkg::*;
    import PerfPkg::*;
#(
    parameter int unsigned SP_PER_SM = 32,
    parameter string MEMORY_INIT = "empty.mem",
    parameter int unsigned INTERFACE_VERSION,
    parameter int unsigned CLOCK_KHZ,
    parameter int unsigned BUILD_HASH,
    parameter bit BUILD_DIRTY,
    parameter bit DDR_ENABLE
) (
    input logic clk,
    input logic rst_n,

    output logic o_core_idle,
    output logic o_core_running,

    // Host request signals
    input logic i_req_valid,
    output logic o_req_ready,
    input logic i_req_write,
    input word_t i_req_addr,
    input word_t i_req_wdata,
    input strb_t i_req_wstrb,

    // Host response signals
    output logic o_rsp_valid,
    input logic i_rsp_ready,
    output word_t o_rsp_rdata,
    output rsp_status_t o_rsp_status,

    output logic o_irq,

    // DDR AXI4 master, flat so the IP wrapper can expose it as m00_axi
    output axi_id_t    m_axi_awid,
    output axi_addr_t  m_axi_awaddr,
    output logic [7:0] m_axi_awlen,
    output logic [2:0] m_axi_awsize,
    output logic [1:0] m_axi_awburst,
    output logic       m_axi_awlock,
    output logic [3:0] m_axi_awcache,
    output logic [2:0] m_axi_awprot,
    output logic [3:0] m_axi_awqos,
    output logic       m_axi_awvalid,
    input  logic       m_axi_awready,

    output axi_data_t  m_axi_wdata,
    output axi_strb_t  m_axi_wstrb,
    output logic       m_axi_wlast,
    output logic       m_axi_wvalid,
    input  logic       m_axi_wready,

    input  axi_id_t    m_axi_bid,
    input  logic [1:0] m_axi_bresp,
    input  logic       m_axi_bvalid,
    output logic       m_axi_bready,

    output axi_id_t    m_axi_arid,
    output axi_addr_t  m_axi_araddr,
    output logic [7:0] m_axi_arlen,
    output logic [2:0] m_axi_arsize,
    output logic [1:0] m_axi_arburst,
    output logic       m_axi_arlock,
    output logic [3:0] m_axi_arcache,
    output logic [2:0] m_axi_arprot,
    output logic [3:0] m_axi_arqos,
    output logic       m_axi_arvalid,
    input  logic       m_axi_arready,

    input  axi_id_t    m_axi_rid,
    input  axi_data_t  m_axi_rdata,
    input  logic [1:0] m_axi_rresp,
    input  logic       m_axi_rlast,
    input  logic       m_axi_rvalid,
    output logic       m_axi_rready
);
    // tdb was here...

    // Control for the core
    core_state_t core_state;
    logic core_complete, complete_pulse, stopped, faulted;
    logic control_start, control_stop, clear_stopped, clear_faulted;
    logic core_reset, memory_quiet;

    // Faults: SM capture (until the next START) and memory subsystem lock-up
    logic core_fault;
    logic [SP_PER_SM-1:0] fault_lanes;
    mem_status_kinds_t fault_kinds;
    pc_t fault_pc;
    logic memory_fatal;
    mem_fatal_t memory_fatal_code;
    assign core_reset = core_state == CORE_RESET;
    assign o_core_idle = core_state == CORE_IDLE;
    assign o_core_running = core_state == CORE_RUNNING;

    // Performance counters: the SM's warp leaves and the memory state they need
    perf_warp_leaf_t warp_leaf [WARPS_PER_SM];
    logic [SP_PER_SM-1:0] perf_st_waiting, perf_st_admitted, perf_ld_waiting, perf_ld_admitted;
    logic perf_wr_slot_free, perf_rd_slot_free;
    logic perf_w_pending;
    logic [$clog2(AXI_MAX_OUTSTANDING_WRITES):0] perf_wr_inflight, perf_wr_owed;
    logic [$clog2(SP_PER_SM+1)-1:0] perf_wr_lane_stores, perf_rd_lane_loads;
    logic [$clog2(AXI_MAX_OUTSTANDING_READS):0] perf_rd_owed;
    logic [$clog2(BRAM_PORTS+1)-1:0] perf_bram_accesses, perf_bram_deferred;
    logic perf_hit;
    word_t perf_rdata;

    // CSR access description/commit. Register actions go directly to State.
    logic csr_write_fire;
    word_t csr_rdata;
    rsp_status_t csr_status;

    // Memory interfaces 
    MemoryInterface #(.ADDR_WIDTH(IMEM_AW)) host_imem_if ();
    MemoryInterface #(.ADDR_WIDTH(IMEM_AW)) smx_imem_if ();
    MemoryInterface #(.ADDR_WIDTH(IMEM_AW)) imem_if ();
    MemoryInterface #(.ADDR_WIDTH(DMEM_AW)) host_dmem_if ();
    MemorySubsystemInterface smx_dmem_if [SP_PER_SM] () ;
    MemorySubsystemInterface dmem_if [SP_PER_SM] ();

    // Instruction memory multiplexing
    assign host_imem_if.rdata = imem_if.rdata;

    assign imem_if.addr = ~o_core_idle ? smx_imem_if.addr : host_imem_if.addr;
    assign imem_if.wdata = host_imem_if.wdata;
    assign imem_if.ren = ~o_core_idle ? smx_imem_if.ren : host_imem_if.ren;
    assign imem_if.wen = ~o_core_idle ? '0 : host_imem_if.wen;

    MMIOController mmio (
        .clk(clk), .rst_n(rst_n),
        .i_req_valid(i_req_valid), .o_req_ready(o_req_ready),
        .i_req_write(i_req_write), .i_req_addr(i_req_addr),
        .i_req_wdata(i_req_wdata), .i_req_wstrb(i_req_wstrb),
        .o_rsp_valid(o_rsp_valid), .i_rsp_ready(i_rsp_ready),
        .o_rsp_rdata(o_rsp_rdata), .o_rsp_status(o_rsp_status),
        .i_idle(o_core_idle), .imem(host_imem_if), .dmem(host_dmem_if),
        .o_csr_write_fire(csr_write_fire),
        .i_csr_rdata(csr_rdata), .i_csr_status(csr_status)
    );

    CSRBank #(
        .SP_PER_SM(SP_PER_SM), .INTERFACE_VERSION(INTERFACE_VERSION), .CLOCK_KHZ(CLOCK_KHZ),
        .BUILD_HASH(BUILD_HASH), .BUILD_DIRTY(BUILD_DIRTY), .DDR_ENABLE(DDR_ENABLE)
    ) regs (
        .clk(clk), .rst_n(rst_n),
        .i_write(i_req_write), .i_addr(i_req_addr), .i_wdata(i_req_wdata),
        .i_byte_en(i_req_wstrb), .i_write_fire(csr_write_fire),
        .o_rdata(csr_rdata), .o_status(csr_status),
        .i_idle(o_core_idle), .i_running(o_core_running), .i_stopped(stopped),
        .i_faulted(faulted), .i_complete_pulse(complete_pulse),
        .i_fault(core_fault), .i_fault_lanes(fault_lanes), .i_fault_kinds(fault_kinds),
        .i_fault_pc(fault_pc), .i_fatal(memory_fatal), .i_fatal_code(memory_fatal_code),
        .i_perf_hit(perf_hit), .i_perf_rdata(perf_rdata),
        .o_start(control_start), .o_stop(control_stop),
        .o_clear_stopped(clear_stopped), .o_clear_faulted(clear_faulted), .o_irq(o_irq)
    );

    ExecutionController state (
        .clk(clk), .rst_n(rst_n),
        .i_start(control_start), .i_stop(control_stop),
        .i_clear_stopped(clear_stopped), .i_clear_faulted(clear_faulted),
        .i_core_complete(core_complete), .i_fault(core_fault),
        .i_memory_quiet(memory_quiet), .i_fatal(memory_fatal),
        .o_core_state(core_state), .o_stopped(stopped), .o_faulted(faulted),
        .o_complete_pulse(complete_pulse)
    );

    StreamingMultiprocessor #(
        .NUM_CORES(SP_PER_SM)
    ) smx (
        .clk(clk),
        .rst_n(rst_n && !core_reset),
        .i_enable(o_core_running),
        .i_ifid_instruction(imem_if.rdata),
        .o_imem_addr(smx_imem_if.addr),
        .o_imem_ren(smx_imem_if.ren),

        .memory_bus(smx_dmem_if),

        .o_kernel_complete(core_complete),

        .o_fault(core_fault),
        .o_fault_lanes(fault_lanes),
        .o_fault_kinds(fault_kinds),
        .o_fault_pc(fault_pc),

        .i_perf_st_waiting(perf_st_waiting),
        .i_perf_st_admitted(perf_st_admitted),
        .i_perf_ld_waiting(perf_ld_waiting),
        .i_perf_ld_admitted(perf_ld_admitted),
        .i_perf_wr_slot_free(perf_wr_slot_free),
        .i_perf_rd_slot_free(perf_rd_slot_free),
        .o_perf_leaf(warp_leaf)
    );

    //! Instruction memory (BRAM)

    (* dont_touch = `DEBUG *)
    MemorySinglePort #(
        .DEPTH(IMEM_ENTRIES),
        .INIT_FILE(MEMORY_INIT)
    ) instructionMemory (
        .clk(clk),
        .memory(imem_if.slave)
    );

    //! Data memory (BRAM + DRAM)

    // Host request built from the word-addressed MMIO DMEM port.
    mem_req_t host_req;
    logic host_req_valid;
    assign host_req_valid = host_dmem_if.ren;
    assign host_req.write = host_dmem_if.wen;
    assign host_req.addr = word_t'(host_dmem_if.addr) << 2; // DMEM base = 0: word index -> byte address
    assign host_req.wdata = host_dmem_if.wdata;
    assign host_req.wstrb = host_dmem_if.wen ? '1 : '0; // host does full-word writes
    assign host_dmem_if.rdata = dmem_if[0].rsp.rdata;
 
    // Slot 0: SMX while not idle, host while idle. Slots 1..N-1: SMX only.
    // While idle the subsystem belongs to the host: SMX requests left over
    // from a STOP are not presented, so they can never be claimed.
    for (genvar i = 0; i < SP_PER_SM; i++) begin : g_req_mux
        if (i == 0) begin : g_host_shared
            // request side
            assign dmem_if[0].req_valid = ~o_core_idle ? smx_dmem_if[0].req_valid : host_req_valid;
            assign dmem_if[0].req = ~o_core_idle ? smx_dmem_if[0].req : host_req;
            assign dmem_if[0].rsp_ready = ~o_core_idle ? smx_dmem_if[0].rsp_ready : 1'b1;
            // response side back to the SMX (gated off while the host owns the slot)
            assign smx_dmem_if[0].req_ready = o_core_running & dmem_if[0].req_ready;
            assign smx_dmem_if[0].rsp_valid = o_core_running & dmem_if[0].rsp_valid;
            assign smx_dmem_if[0].rsp = dmem_if[0].rsp;
        end else begin : g_core_only
            assign dmem_if[i].req_valid = ~o_core_idle & smx_dmem_if[i].req_valid;
            assign dmem_if[i].req = smx_dmem_if[i].req;
            assign dmem_if[i].rsp_ready = smx_dmem_if[i].rsp_ready;
            assign smx_dmem_if[i].req_ready = dmem_if[i].req_ready;
            assign smx_dmem_if[i].rsp_valid = dmem_if[i].rsp_valid;
            assign smx_dmem_if[i].rsp = dmem_if[i].rsp;
        end
    end

    //! DDR AXI4 master: the subsystem's interface, flattened onto the ports

    AXI4FullInterface axi_if ();

    // AW
    assign m_axi_awid    = axi_if.aw.id;
    assign m_axi_awaddr  = axi_if.aw.addr;
    assign m_axi_awlen   = axi_if.aw.len;
    assign m_axi_awsize  = axi_if.aw.size;
    assign m_axi_awburst = axi_if.aw.burst;
    assign m_axi_awlock  = axi_if.aw.lock;
    assign m_axi_awcache = axi_if.aw.cache;
    assign m_axi_awprot  = axi_if.aw.prot;
    assign m_axi_awqos   = axi_if.aw.qos;
    assign m_axi_awvalid = axi_if.aw_valid;
    assign axi_if.aw_ready = m_axi_awready;

    // W
    assign m_axi_wdata  = axi_if.w.data;
    assign m_axi_wstrb  = axi_if.w.strb;
    assign m_axi_wlast  = axi_if.w.last;
    assign m_axi_wvalid = axi_if.w_valid;
    assign axi_if.w_ready = m_axi_wready;

    // B
    assign axi_if.b.id   = m_axi_bid;
    assign axi_if.b.resp = axi_resp_t'(m_axi_bresp);
    assign axi_if.b_valid = m_axi_bvalid;
    assign m_axi_bready  = axi_if.b_ready;

    // AR
    assign m_axi_arid    = axi_if.ar.id;
    assign m_axi_araddr  = axi_if.ar.addr;
    assign m_axi_arlen   = axi_if.ar.len;
    assign m_axi_arsize  = axi_if.ar.size;
    assign m_axi_arburst = axi_if.ar.burst;
    assign m_axi_arlock  = axi_if.ar.lock;
    assign m_axi_arcache = axi_if.ar.cache;
    assign m_axi_arprot  = axi_if.ar.prot;
    assign m_axi_arqos   = axi_if.ar.qos;
    assign m_axi_arvalid = axi_if.ar_valid;
    assign axi_if.ar_ready = m_axi_arready;

    // R
    assign axi_if.r.id   = m_axi_rid;
    assign axi_if.r.data = m_axi_rdata;
    assign axi_if.r.resp = axi_resp_t'(m_axi_rresp);
    assign axi_if.r.last = m_axi_rlast;
    assign axi_if.r_valid = m_axi_rvalid;
    assign m_axi_rready  = axi_if.r_ready;

    MemorySubsystem #(
        .NUM_REQ(SP_PER_SM),
        .DDR_ENABLE(DDR_ENABLE)
    ) memory_subsystem (
        .clk(clk),
        .rst_n(rst_n),
        .i_req_enable(o_core_running | o_core_idle),
        .memory_if(dmem_if),
        .axi_if(axi_if),
        .o_idle(memory_quiet),
        .o_fatal(memory_fatal),
        .o_fatal_code(memory_fatal_code),
        .o_perf_st_waiting(perf_st_waiting),
        .o_perf_st_admitted(perf_st_admitted),
        .o_perf_ld_waiting(perf_ld_waiting),
        .o_perf_ld_admitted(perf_ld_admitted),
        .o_perf_wr_slot_free(perf_wr_slot_free),
        .o_perf_rd_slot_free(perf_rd_slot_free),
        .o_perf_w_pending(perf_w_pending),
        .o_perf_wr_inflight(perf_wr_inflight),
        .o_perf_wr_owed(perf_wr_owed),
        .o_perf_wr_lane_stores(perf_wr_lane_stores),
        .o_perf_rd_owed(perf_rd_owed),
        .o_perf_rd_lane_loads(perf_rd_lane_loads),
        .o_perf_bram_accesses(perf_bram_accesses),
        .o_perf_bram_deferred(perf_bram_deferred)
    );

    //! Performance counters
    PerfCounters #(
        .NUM_WARPS(WARPS_PER_SM),
        .SP_PER_SM(SP_PER_SM),
        .WR_SLOTS(AXI_MAX_OUTSTANDING_WRITES),
        .RD_SLOTS(AXI_MAX_OUTSTANDING_READS),
        .BRAM_PORTS(BRAM_PORTS)
    ) perf (
        .clk(clk),
        .rst_n(rst_n),
        .i_core_state(core_state),
        .i_warp_leaf(warp_leaf),
        .i_aw_valid(axi_if.aw_valid),
        .i_aw_ready(axi_if.aw_ready),
        .i_w_valid(axi_if.w_valid),
        .i_w_ready(axi_if.w_ready),
        .i_w_pending(perf_w_pending),
        .i_wr_inflight(perf_wr_inflight),
        .i_wr_owed(perf_wr_owed),
        .i_wr_ring_full(!perf_wr_slot_free),
        .i_wr_lane_stores(perf_wr_lane_stores),
        .i_ar_valid(axi_if.ar_valid),
        .i_ar_ready(axi_if.ar_ready),
        .i_r_valid(axi_if.r_valid),
        .i_r_ready(axi_if.r_ready),
        .i_rd_owed(perf_rd_owed),
        .i_rd_lane_loads(perf_rd_lane_loads),
        .i_bram_accesses(perf_bram_accesses),
        .i_bram_deferred(perf_bram_deferred),
        .i_addr(i_req_addr),
        .o_hit(perf_hit),
        .o_rdata(perf_rdata)
    );

endmodule
