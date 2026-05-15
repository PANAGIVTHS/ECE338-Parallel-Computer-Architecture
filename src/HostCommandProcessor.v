module HostCommandProcessor (
    input i_clk,
    input i_rst,

    // Core state
    input [1:0] i_core_state,

    // Read data signals
    input [31:0] i_dmem_rdata,
    input [31:0] i_reg_rdata,

    // Host command signals
    input wire [2:0] i_host_command,
    input wire i_host_command_valid,
    input wire [31:0] i_host_address,
    input wire [31:0] i_host_wdata,

    output reg [31:0] o_host_address,
    output reg [31:0] o_host_wdata, 
    output reg [31:0] o_host_rdata,
    output reg o_host_busy,
    output reg o_host_done,

    // GPU control signals interface
    output reg o_host_imem_wen,
    output reg o_host_done_writing,
    output reg o_host_done_dumping
);
    localparam CMD_IMEM_WRITE = 3'd0;
    localparam CMD_WRITE_DONE = 3'd1;
    localparam CMD_DMEM_READ = 3'd2;
    localparam CMD_REG_READ = 3'd3;
    localparam CMD_READ_DONE = 3'd4;

    localparam S_IDLE = 3'd0;
    localparam S_ACCEPT = 3'd1;
    localparam S_WRITE = 3'd2;
    localparam S_READ = 3'd3;
    localparam S_DONE = 3'd5;

    reg [2:0] host_command;
    reg [2:0] current_state, next_state;

    always @(posedge i_clk) begin
        if (!i_rst) begin
            current_state <= S_IDLE;
        end else begin
            current_state <= next_state;
        end
    end

    always @(*) begin
        case (current_state)
            S_IDLE: next_state = i_host_command_valid ? S_ACCEPT : S_IDLE;
            S_ACCEPT: begin
                case (host_command)

                    CMD_IMEM_WRITE,
                    CMD_WRITE_DONE,
                    CMD_READ_DONE: begin
                        next_state = S_WRITE;
                    end

                    CMD_DMEM_READ,
                    CMD_REG_READ: begin
                        next_state = S_READ;
                    end

                    default: begin
                        next_state = S_DONE;
                    end

                endcase
            end
            S_WRITE: next_state = S_DONE;
            S_READ: next_state = S_DONE;
            S_DONE: next_state = !i_host_command_valid ? S_IDLE : S_DONE;
            default: next_state = S_IDLE;
        endcase
    end

    always @(*) begin
        o_host_busy = 1'b0;
        o_host_done = 1'b0;
        o_host_imem_wen = 1'b0;
        o_host_done_writing = 1'b0;
        o_host_done_dumping = 1'b0;

        case (current_state)
            S_ACCEPT: begin
                o_host_busy = 1'b1;
            end
            S_WRITE: begin
                o_host_busy = 1'b1;
                case (host_command)
                    CMD_IMEM_WRITE: begin
                        if (i_core_state == `CORE_LOADING)
                            o_host_imem_wen = 1'b1;
                    end
                    CMD_WRITE_DONE: begin
                        if (i_core_state == `CORE_LOADING)
                            o_host_done_writing = 1'b1;
                    end
                    CMD_READ_DONE: begin
                        if (i_core_state == `CORE_DUMPING)
                            o_host_done_dumping = 1'b1;
                    end
                endcase
            end
            S_READ: begin
                o_host_busy = 1'b1;
            end
            S_DONE: begin
                o_host_busy = 1'b0;
                o_host_done = 1'b1;
            end
        endcase
    end

    always @(posedge i_clk) begin
        if (!i_rst) begin
            host_command <= 3'b0;
            o_host_address <= 32'b0;
            o_host_wdata <= 32'b0;
        end else if (i_host_command_valid && current_state == S_IDLE) begin
            host_command <= i_host_command;
            o_host_address <= i_host_address;
            o_host_wdata <= i_host_wdata;
        end
    end

    always @(posedge i_clk) begin
        if (!i_rst) begin
            o_host_rdata <= 32'b0;
        end else if (current_state == S_READ) begin
            case (host_command)
                CMD_DMEM_READ: o_host_rdata <= i_dmem_rdata; 
                CMD_REG_READ: o_host_rdata <= i_reg_rdata;
            endcase
        end
    end
    
endmodule