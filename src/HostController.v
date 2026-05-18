module HostController (
    input clk,
    input rst,
    input i_core_complete,
    input [31:0] i_dmem_rdata,
    input [31:0] i_reg_rdata,

    // Host CPU control signals
    input wire [2:0] i_host_command,
    input wire i_host_command_valid,
    input wire [31:0] i_host_address,
    input wire [31:0] i_host_wdata,
    
    output wire [31:0] o_host_address,
    output wire [31:0] o_host_wdata, 
    output wire [31:0] o_host_rdata,
    output wire o_host_imem_wen,
    output wire o_host_dmem_wen,
    output wire o_host_busy,
    output wire o_host_done,

    // GPU control
    output reg [1:0] o_core_state
);
    (* mark_debug = "true" *) reg [1:0] current_state, next_state;
    wire host_done_writing, host_done_dumping;

    always @(posedge clk) begin
        if (!rst) begin
            current_state <= `CORE_LOADING;
        end else begin
            current_state <= next_state;
        end
    end

    always @(*) begin
        case (current_state)
            `CORE_LOADING: next_state = host_done_writing ? `CORE_RUNNING : `CORE_LOADING;
            `CORE_RUNNING: next_state = i_core_complete ? `CORE_DUMPING : `CORE_RUNNING;
            `CORE_DUMPING: next_state = host_done_dumping ? `CORE_LOADING : `CORE_DUMPING;
            default: next_state = `CORE_LOADING;
        endcase
    end

    always @(*) begin
        case (current_state)
            `CORE_LOADING: begin
                o_core_state = `CORE_LOADING;
            end
            `CORE_RUNNING: begin
                o_core_state = `CORE_RUNNING;
            end 
            `CORE_DUMPING: begin
                o_core_state = `CORE_DUMPING;
            end
            default: begin
                o_core_state = `CORE_LOADING;
            end
        endcase
    end

    HostCommandProcessor host_command_processor (
        .clk(clk),
        .rst(rst),
        .i_core_state(o_core_state),
        .i_dmem_rdata(i_dmem_rdata),
        .i_reg_rdata(i_reg_rdata),
        .i_host_command(i_host_command),
        .i_host_command_valid(i_host_command_valid),
        .i_host_address(i_host_address),
        .i_host_wdata(i_host_wdata),

        .o_host_address(o_host_address),
        .o_host_wdata(o_host_wdata),
        .o_host_rdata(o_host_rdata),
        .o_host_imem_wen(o_host_imem_wen),
        .o_host_dmem_wen(o_host_dmem_wen),
        .o_host_busy(o_host_busy),
        .o_host_done(o_host_done),

        .o_host_done_writing(host_done_writing),
        .o_host_done_dumping(host_done_dumping)
    );
    
endmodule