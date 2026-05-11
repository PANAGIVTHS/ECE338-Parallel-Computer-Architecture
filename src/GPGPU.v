module GPGPU (
    input wire i_clk,
    input wire i_rst,
    input wire i_uart_rx,
    output wire o_uart_tx
);
    // tdb was here...
    wire clk;
    wire [31:0] ifid_instruction, dmem_read_data, dmem_write_data;
    wire [9:0] dmem_addr;
    wire [$clog2(`IMEM_ENTRIES)-1:0] imem_addr;
    wire imem_ren, dmem_ren, dmem_wen;

    StreamingProcessor sp (
        .i_clk(clk),
        .i_rst(i_rst), 
        .i_ifid_instruction(ifid_instruction),
        .i_dmem_read_data(dmem_read_data),
        .o_imem_addr(imem_addr), 
        .o_imem_ren(imem_ren),
        .o_dmem_addr(dmem_addr),
        .o_dmem_ren(dmem_ren),
        .o_dmem_wen(dmem_wen),
        .o_dmem_write_data(dmem_write_data)
    );

    (* dont_touch = "true" *)
    MemorySinglePort #(
        .DEPTH(`IMEM_ENTRIES),
        .INIT_FILE("")
    ) instructionMemory (
        .clk(clk),
        .i_addr_a(imem_addr),
        .i_ren_a(imem_ren),
        .i_wen_a(1'b0),
        .i_data_a(32'b0),
        .o_out_a(ifid_instruction)
    );

    (* dont_touch = "true" *)
    MemoryDualPort #(
        .DEPTH(1024),
        .INIT_FILE("")
    ) dataMemory (
        .clk(clk),
        .i_addr_a(dmem_addr),
        .i_ren_a(dmem_ren),
        .i_wen_a(dmem_wen),
        .i_data_a(dmem_write_data),
        .o_out_a(dmem_read_data),
        .i_addr_b(10'b0),
        .i_ren_b(1'b0),
        .i_wen_b(1'b0),
        .i_data_b(32'b0),
        .o_out_b()
    );

    clk_wiz_0 clockDivider (
        .clk_in1(i_clk),
        .clk_out1(clk)
    );

endmodule
