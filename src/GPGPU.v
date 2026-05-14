module GPGPU (
    input wire i_clk,
    input wire i_rst,
    input wire i_uart_rx,
    output wire o_uart_tx,
    output wire o_ferror,
    output wire o_perror,
    output wire o_loading,
    output wire o_running,
    output wire o_dumping
);
    // tdb was here...
    wire clk;
    
    // Host control for the core
    wire core_run, core_clear;
    
    // Host controller memory signals
    wire [9:0] host_dmem_addr;
    wire [$clog2(`IMEM_ENTRIES)-1:0] host_imem_addr;
    wire [31:0] host_imem_wdata;
    wire host_imem_wen;
    
    // Streaming processor memory signals
    wire [9:0] core_dmem_addr;
    wire [$clog2(`IMEM_ENTRIES)-1:0] core_imem_addr;
    wire [31:0] core_dmem_wdata;
    wire core_imem_ren, core_dmem_ren, core_dmem_wen;

    // MUX-ed memory signals
    wire [9:0] dmem_addr;
    wire [$clog2(`IMEM_ENTRIES)-1:0] imem_addr;
    wire [31:0] imem_rdata, dmem_rdata, dmem_wdata;
    wire imem_ren, dmem_ren, dmem_wen;

    assign dmem_addr = core_run ? core_dmem_addr : host_dmem_addr;
    assign imem_addr = core_run ? core_imem_addr : host_imem_addr;
    assign dmem_wdata = core_run ? core_dmem_wdata : 32'b0;
    assign imem_ren = core_run ? core_imem_ren : 1'b1;
    assign dmem_ren = core_run ? core_dmem_ren : 1'b1;
    assign dmem_wen = core_run ? core_dmem_wen : 1'b0;
    assign o_loading = !core_run && core_clear;
    assign o_running = core_run;
    assign o_dumping = !core_run && !core_clear;

    HostController host_controller (
        .i_clk(i_clk),
        .i_rst(i_rst),
        .i_core_complete(1'b0),
        .i_uart_rx(i_uart_rx),
        .o_uart_tx(o_uart_tx),
        .o_core_run(core_run),
        .o_core_clear(core_clear),
        .o_imem_addr(host_imem_addr),
        .o_imem_wdata(host_imem_wdata),
        .o_imem_wen(host_imem_wen),
        .o_dmem_addr(host_dmem_addr),
        .i_dmem_rdata(dmem_rdata),
        .o_reg_addr(),
        .i_reg_rdata(),
        .o_ferror(o_ferror),
        .o_perror(o_perror)
    );

    StreamingProcessor sp (
        .i_clk(i_clk),
        .i_rst(i_rst && !core_clear),
        .i_enable(core_run),
        .i_ifid_instruction(imem_rdata),
        .i_dmem_rdata(dmem_rdata),
        .o_imem_addr(core_imem_addr), 
        .o_imem_ren(core_imem_ren),
        .o_dmem_addr(core_dmem_addr),
        .o_dmem_ren(core_dmem_ren),
        .o_dmem_wen(core_dmem_wen),
        .o_dmem_wdata(core_dmem_wdata)
    );

    (* dont_touch = `DEBUG *)
    MemorySinglePort #(
        .DEPTH(`IMEM_ENTRIES),
        .INIT_FILE("")
    ) instructionMemory (
        .clk(i_clk),
        .i_addr_a(imem_addr),
        .i_ren_a(imem_ren),
        .i_wen_a(host_imem_wen),
        .i_data_a(host_imem_wdata),
        .o_out_a(imem_rdata)
    );

    (* dont_touch = `DEBUG *)
    MemoryDualPort #(
        .DEPTH(1024),
        .INIT_FILE("")
    ) dataMemory (
        .clk(i_clk),
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

    // clk_wiz_0 clockDivider (
    //     .clk_in1(i_clk),
    //     .clk_out1(clk)
    // );

endmodule
