module HostController (
    input i_clk,
    input i_rst,
    input i_core_complete,

    // UART Physical Interface
    input i_uart_rx,
    output o_uart_tx,

    // GPU control
    output reg o_core_run,
    output reg o_core_clear,

    // Instruction Memory interfaces
    output [$clog2(`IMEM_ENTRIES)-1:0] o_imem_addr,
    output [31:0] o_imem_wdata,
    output o_imem_wen, 

    // Data Memory interfaces
    output wire [9:0] o_dmem_addr,
    input wire [31:0] i_dmem_rdata,
    output wire [4:0] o_reg_addr,
    input wire [31:0] i_reg_rdata,

    // Error handling
    output reg o_ferror,
    output reg o_perror
);
    localparam LOAD = 3'b000;
    localparam RUN = 3'b001;
    localparam DONE = 3'b010;
    localparam FERROR = 3'b011;
    localparam PERROR = 3'b100;

    (* mark_debug = "true" *) reg [2:0] current_state, next_state;
    wire program_ready, dump_ready, rx_ferror, rx_perror;

    always @(posedge i_clk) begin
        if (!i_rst) begin
            current_state <= LOAD;
        end else begin
            current_state <= next_state;
        end
    end

    always @(*) begin
        if (rx_ferror) begin
            next_state = FERROR;
        end else if (rx_perror) begin
            next_state = PERROR;
        end else begin
            case (current_state)
                LOAD: next_state = program_ready ? RUN : LOAD;
                RUN: next_state = i_core_complete ? DONE : RUN;
                DONE: next_state = dump_ready ? LOAD : DONE;
                FERROR: next_state = FERROR;
                PERROR: next_state = PERROR;
                default: next_state = LOAD;
            endcase
        end
    end

    always @(*) begin
        case (current_state)
            LOAD: begin
                o_core_run = 1'b0;
                o_core_clear = 1'b1;
                o_ferror = 1'b0;
                o_perror = 1'b0;
            end
            RUN: begin
                o_core_run = 1'b1;
                o_core_clear = 1'b0;
                o_ferror = 1'b0;
                o_perror = 1'b0;
            end 
            DONE: begin
                o_core_run = 1'b0;
                o_core_clear = 1'b0;
                o_ferror = 1'b0;
                o_perror = 1'b0;
            end
            PERROR: begin
                o_core_run = 1'b0;
                o_core_clear = 1'b0;
                o_ferror = 1'b0;
                o_perror = 1'b1;
            end
            FERROR: begin
                o_core_run = 1'b0;
                o_core_clear = 1'b0;
                o_ferror = 1'b1;
                o_perror = 1'b0;
            end
            default: begin
                o_core_run = 1'b0;
                o_core_clear = 1'b1;
                o_ferror = 1'b0;
                o_perror = 1'b0;
            end
        endcase
    end

    uart_controller uart_controller (
        .i_clk(i_clk),
        .i_rst(i_rst),
        .i_error(rx_perror || rx_ferror),
        .i_uart_rx(i_uart_rx),
        .o_uart_tx(o_uart_tx),
        .i_tx_enable(!o_core_run && !o_core_clear),
        .i_rx_enable(!o_core_run && o_core_clear),
        .o_imem_addr(o_imem_addr),
        .o_imem_wdata(o_imem_wdata),
        .o_imem_wen(o_imem_wen),
        .o_dmem_addr(o_dmem_addr),
        .i_dmem_rdata(i_dmem_rdata),
        .o_reg_addr(o_reg_addr),
        .i_reg_rdata(i_reg_rdata),
        .o_program_ready(program_ready),
        .o_dump_ready(dump_ready),
        .o_perror(rx_perror),
        .o_ferror(rx_ferror)
    );
    
endmodule