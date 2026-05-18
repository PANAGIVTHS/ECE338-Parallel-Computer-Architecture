module GPGPU (
    input wire clk_in,
    input wire rst,
    output wire o_loading,
    output wire o_running,
    output wire o_dumping,
    
    // Host CPU commands
    input wire [2:0] i_host_command,
    input wire i_host_command_valid,
    input wire [31:0] i_host_address,
    input wire [31:0] i_host_wdata,

    // Host CPU outputs
    output wire [31:0] o_host_rdata,
    output wire o_host_busy,
    output wire o_host_done
);
    // tdb was here...
    wire clk;
    // assign clk = clk_in;
    
    // Control for the core
    wire [1:0] core_state;
    wire core_run, core_clear;
    wire core_complete;

    // Host memory signals
    wire [31:0] host_address, host_wdata;
    wire host_imem_wen;
    
    // SMX memory signals
    wire [`DMEM_AW-1:0] core_dmem_addr;
    wire [`IMEM_AW-1:0] core_imem_addr;
    wire [31:0] core_dmem_wdata;
    wire core_imem_ren, core_dmem_ren, core_dmem_wen;

    // MUX-ed memory signals
    wire [`DMEM_AW-1:0] dmem_addr;
    wire [`IMEM_AW-1:0] imem_addr;
    wire [31:0] imem_rdata, imem_wdata, dmem_rdata, dmem_wdata, reg_rdata;
    wire imem_ren, imem_wen, dmem_ren, dmem_wen;

    assign core_run = core_state == `CORE_RUNNING;
    assign core_clear = core_state == `CORE_LOADING;
    assign o_loading = core_state == `CORE_LOADING;
    assign o_running = core_state == `CORE_RUNNING;
    assign o_dumping = core_state == `CORE_DUMPING;

    assign dmem_addr = core_run ? core_dmem_addr : host_address;
    assign dmem_wdata = core_run ? core_dmem_wdata : 32'b0;
    assign dmem_ren = core_run ? core_dmem_ren : 1'b1;
    assign dmem_wen = core_run ? core_dmem_wen : 1'b0;

    assign imem_addr = core_run ? core_imem_addr : host_address;
    assign imem_wdata = host_wdata;
    assign imem_ren = core_run ? core_imem_ren : 1'b1;
    assign imem_wen = core_run ? 1'b0 : host_imem_wen;

    HostController host_controller (
        .clk(clk),
        .rst(rst),
        .i_core_complete(core_complete),
        .i_reg_rdata(reg_rdata),
        .i_dmem_rdata(dmem_rdata),

        .i_host_command(i_host_command),
        .i_host_command_valid(i_host_command_valid),
        .i_host_address(i_host_address),
        .i_host_wdata(i_host_wdata),

        .o_host_address(host_address),
        .o_host_wdata(host_wdata),
        .o_host_imem_wen(host_imem_wen),
        .o_host_rdata(o_host_rdata),
        .o_host_busy(o_host_busy),
        .o_host_done(o_host_done),

        .o_core_state(core_state)
    );

    StreamingMultiprocessor #(
        .NUM_CORES(2)
    ) smx (
        .clk(clk),
        .rst(rst),
        .i_enable(core_run),
        .i_ifid_instruction(imem_rdata),
        .i_dmem_rdata(dmem_rdata),
        .o_imem_addr(core_imem_addr),
        .o_imem_ren(core_imem_ren),
        .o_dmem_addr(core_dmem_addr),
        .o_dmem_ren(core_dmem_ren),
        .o_dmem_wen(core_dmem_wen),
        .o_dmem_wdata(core_dmem_wdata),
        .o_kernel_complete(core_complete)
    );

    (* dont_touch = `DEBUG *)
    MemorySinglePort #(
        .DEPTH(`IMEM_ENTRIES),
        .INIT_FILE("program.mem")
    ) instructionMemory (
        .clk(clk),
        .i_addr_a(imem_addr),
        .i_ren_a(imem_ren),
        .i_wen_a(imem_wen),
        .i_data_a(imem_wdata),
        .o_out_a(imem_rdata)
    );

    clk_wiz_0 clockDivider (
        .clk_in1(clk_in),
        .clk_out1(clk)
    );

endmodule
