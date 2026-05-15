module GPGPU (
    input wire i_clk,
    input wire i_rst,
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
    assign clk = i_clk;
    
    // Control for the core
    wire [1:0] core_state;
    wire core_run, core_clear;

    // Host memory signals
    wire [31:0] host_address, host_wdata;
    wire host_imem_wen;
    
    // Streaming processor memory signals
    wire [9:0] core_dmem_addr;
    wire [$clog2(`IMEM_ENTRIES)-1:0] core_imem_addr;
    wire [31:0] core_dmem_wdata;
    wire core_imem_ren, core_dmem_ren, core_dmem_wen;

    // MUX-ed memory signals
    wire [9:0] dmem_addr;
    wire [$clog2(`IMEM_ENTRIES)-1:0] imem_addr;
    wire [31:0] imem_rdata, dmem_rdata, reg_rdata, dmem_wdata;
    wire imem_ren, imem_wen, dmem_ren, dmem_wen;

    assign core_run = core_state == `CORE_RUNNING;
    assign core_clear = core_state == `CORE_LOADING;
    assign dmem_addr = core_run ? core_dmem_addr : host_address;
    assign imem_addr = core_run ? core_imem_addr : host_address;
    assign dmem_wdata = core_run ? core_dmem_wdata : 32'b0;
    assign imem_ren = core_run ? core_imem_ren : 1'b1;
    assign imem_wen = core_run ? 1'b0 : host_imem_wen;
    assign dmem_ren = core_run ? core_dmem_ren : 1'b1;
    assign dmem_wen = core_run ? core_dmem_wen : 1'b0;
    assign o_loading = core_state == `CORE_LOADING;
    assign o_running = core_state == `CORE_RUNNING;
    assign o_dumping = core_state == `CORE_DUMPING;

    HostController host_controller (
        .i_clk(clk),
        .i_rst(i_rst),
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

    StreamingProcessor sp (
        .i_clk(clk),
        .i_rst(i_rst && !core_clear),
        .i_enable(core_run),
        .i_ifid_instruction(imem_rdata),
        .i_dmem_rdata(dmem_rdata),
        .o_imem_addr(core_imem_addr), 
        .o_imem_ren(core_imem_ren),
        .o_dmem_addr(core_dmem_addr),
        .o_dmem_ren(core_dmem_ren),
        .o_dmem_wen(core_dmem_wen),
        .o_dmem_wdata(core_dmem_wdata),
        .i_reg_addr(host_address),
        .o_reg_rdata(reg_rdata),
        .o_core_complete(core_complete)
    );

    (* dont_touch = `DEBUG *)
    MemorySinglePort #(
        .DEPTH(`IMEM_ENTRIES),
        .INIT_FILE("empty.mem")
    ) instructionMemory (
        .clk(clk),
        .i_addr_a(imem_addr),
        .i_ren_a(imem_ren),
        .i_wen_a(imem_wen),
        .i_data_a(host_wdata),
        .o_out_a(imem_rdata)
    );

    (* dont_touch = `DEBUG *)
    MemoryDualPort #(
        .DEPTH(1024),
        .INIT_FILE("empty.mem")
    ) dataMemory (
        .clk(clk),
        .i_addr_a(dmem_addr),
        .i_ren_a(dmem_ren),
        .i_wen_a(dmem_wen),
        .i_data_a(dmem_wdata),
        .o_out_a(dmem_rdata),
        .i_addr_b(10'b0),
        .i_ren_b(1'b0),
        .i_wen_b(1'b0),
        .i_data_b(32'b0),
        .o_out_b()
    );

//    clk_wiz_0 clockDivider (
//        .clk_in1(i_clk),
//        .clk_out1(clk)
//    );

endmodule
