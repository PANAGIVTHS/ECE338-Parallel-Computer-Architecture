module uart_controller (
    input i_clk,
    input i_rst,

    // UART interface
    input i_uart_rx,
    output o_uart_tx,

    // Transmission signals
    input i_tx_enable,
    input i_rx_enable,
    input i_error,

    // Instruction memory
    output reg [$clog2(`IMEM_ENTRIES)-1:0] o_imem_addr,
    output reg [31:0] o_imem_wdata,
    output reg o_imem_wen,
    
    // Data memory and regfile
    output reg [9:0] o_dmem_addr,
    input wire [31:0] i_dmem_rdata,
    output reg [4:0] o_reg_addr,
    input wire [31:0] i_reg_rdata,

    // Status signals
    output reg o_program_ready,
    output reg o_dump_ready,
    
    // Error handling
    output wire o_ferror,
    output wire o_perror
);

    localparam DMEM_BYTES = (2 ** 10) * 4;
    localparam IMEM_BYTES = `IMEM_ENTRIES * 4;
    localparam DMEM_WIDTH = $clog2(DMEM_BYTES);
    localparam IMEM_WIDTH = $clog2(IMEM_BYTES);
    localparam COUNTER_WIDTH = DMEM_WIDTH > IMEM_WIDTH ? DMEM_WIDTH : IMEM_WIDTH;

    // FSM states
    localparam IDLE = 4'd0;
    localparam IMEM_RECEIVE = 4'd1;
    localparam IMEM_WORD_DONE = 4'd2;
    localparam IMEM_DONE = 4'd3;
    localparam DMEM_TRANSMIT = 4'd4;
    localparam DMEM_WORD_DONE = 4'd5;
    localparam DMEM_DONE = 4'd6;
    localparam REG_TRANSMIT = 4'd7;
    localparam REG_WORD_DONE = 4'd8;
    localparam REG_DONE = 4'd9;
    localparam ERROR = 4'd10;

    // FSM signals
    reg [3:0] current_state, next_state;
    reg [31:0] word_buffer;
    (* mark_debug = "true" *) reg [COUNTER_WIDTH:0] byte_counter;

    // Receiver signals
    reg rx_enabled;
    reg rx_valid_l2p [1:0];
    (* mark_debug = "true" *) wire rx_valid, rx_valid_pulse;
    (* mark_debug = "true" *) wire [7:0] rx_data;

    // Transmitter signals
    reg tx_enabled, tx_wr, transmit_dmem, tx_word_done, tx_busy_l2p;
    wire tx_busy, tx_done_pulse;
    reg [7:0] tx_data;

    always @(posedge i_clk) begin
        if (!i_rst) begin
            current_state <= IDLE;
        end else begin
            current_state <= next_state;
        end
    end

    always @(*) begin
        if (i_error) begin
            next_state = ERROR;
        end else begin
            case (current_state)
                IDLE: next_state = i_tx_enable ? DMEM_TRANSMIT : (i_rx_enable ? IMEM_RECEIVE : IDLE);
                IMEM_RECEIVE: next_state = (rx_valid_pulse && byte_counter[1:0] == 2'b11) ? IMEM_WORD_DONE : IMEM_RECEIVE;
                IMEM_WORD_DONE: next_state = (byte_counter == `IMEM_ENTRIES * 4) ? IMEM_DONE : IMEM_RECEIVE;
                IMEM_DONE: next_state = IDLE;
                DMEM_TRANSMIT: next_state = (tx_done_pulse && byte_counter[1:0] == 2'b11) ? DMEM_WORD_DONE : DMEM_TRANSMIT;
                DMEM_WORD_DONE: next_state = (byte_counter == (2 ** 10) * 4) ? DMEM_DONE : DMEM_TRANSMIT;
                DMEM_DONE: next_state = REG_TRANSMIT;
                REG_TRANSMIT: next_state = (tx_done_pulse && byte_counter[1:0] == 2'b11) ? REG_WORD_DONE : REG_TRANSMIT;
                REG_WORD_DONE: next_state = (byte_counter == 32 * 4) ? REG_DONE : REG_TRANSMIT;
                REG_DONE: next_state = IDLE;
                ERROR: next_state = ERROR;
                default: next_state = IDLE;
            endcase
        end
    end

    always @(*) begin
        rx_enabled = 1'b0;
        tx_enabled = 1'b0;
        tx_wr = 1'b0;
        tx_word_done = 1'b0;
        transmit_dmem = 1'b0;
        o_program_ready = 1'b0;
        o_dump_ready = 1'b0;
        o_imem_wen = 1'b0;
        o_imem_wdata = word_buffer;
        o_imem_addr = byte_counter[IMEM_WIDTH:2] - 1;
        o_dmem_addr = byte_counter[DMEM_WIDTH:2];
        o_reg_addr = byte_counter[6:2];

        case (current_state)
            IMEM_RECEIVE: begin
                rx_enabled = 1'b1;
            end
            IMEM_WORD_DONE: begin 
                rx_enabled = 1'b1;
                o_imem_wen = 1'b1;
            end
            IMEM_DONE: begin 
                rx_enabled = 1'b1;
                o_program_ready = 1'b1;
            end
            DMEM_TRANSMIT: begin
                tx_enabled = 1'b1;
                tx_wr = 1'b1;
                transmit_dmem = 1'b1;
            end
            DMEM_WORD_DONE: begin
                tx_enabled = 1'b1;
                tx_wr = 1'b1;
                transmit_dmem = 1'b1;
                tx_word_done = 1'b1;
            end
            DMEM_DONE: begin
                tx_enabled = 1'b1;
                tx_wr = 1'b1;
                transmit_dmem = 1'b1;
            end
            REG_TRANSMIT: begin
                tx_enabled = 1'b1;
                tx_wr = 1'b1;
                transmit_dmem = 1'b0;
            end
            REG_WORD_DONE: begin
                tx_enabled = 1'b1;
                tx_wr = 1'b1;
                transmit_dmem = 1'b0;
                tx_word_done = 1'b1;
            end
            REG_DONE: begin
                tx_enabled = 1'b1;
                tx_wr = 1'b0;
                transmit_dmem = 1'b0;
                o_dump_ready = 1'b1;
            end
            ERROR: begin
                rx_enabled = 1'b1;
            end
        endcase
    end

    // Byte counter for transmitter and receiver
    always @(posedge i_clk) begin
        if (!i_rst) begin
            byte_counter <= 0;
        end else if (current_state == IDLE) begin
            byte_counter <= 0;
        end else if ((i_rx_enable && rx_valid_pulse) || (i_tx_enable && tx_done_pulse)) begin
            byte_counter <= byte_counter + 1;
        end
    end

    // Word buffer holding received bytes
    always @(posedge i_clk) begin
        if (!i_rst) begin
            word_buffer <= 32'b0;
        end else if (i_rx_enable && rx_valid_pulse) begin
            case (byte_counter[1:0])
                2'b00: word_buffer[31:24] <= rx_data;
                2'b01: word_buffer[23:16] <= rx_data;
                2'b10: word_buffer[15:8] <= rx_data;
                2'b11: word_buffer[7:0] <= rx_data;
            endcase
        end
    end

    // Level to pulse on rx_valid
    always @(posedge i_clk) begin
        if (!i_rst) begin
            rx_valid_l2p[0] <= 0;
            rx_valid_l2p[1] <= 0;
        end else begin
            rx_valid_l2p[0] <= rx_valid;
            rx_valid_l2p[1] <= rx_valid_l2p[0];
        end
    end

    assign rx_valid_pulse = !rx_valid_l2p[1] & rx_valid_l2p[0];

    // Transmission data
    always @(*) begin
        if (transmit_dmem) begin
            case (byte_counter[1:0])
                2'b00: tx_data = i_dmem_rdata[31:24];
                2'b01: tx_data = i_dmem_rdata[23:16];
                2'b10: tx_data = i_dmem_rdata[15:8];
                2'b11: tx_data = i_dmem_rdata[7:0];
            endcase 
        end else begin
            case (byte_counter[1:0])
                2'b00: tx_data = i_reg_rdata[31:24];
                2'b01: tx_data = i_reg_rdata[23:16];
                2'b10: tx_data = i_reg_rdata[15:8];
                2'b11: tx_data = i_reg_rdata[7:0];
            endcase 
        end
    end

    // Level to pulse on tx_done
    always @(posedge i_clk) begin
        if (!i_rst) begin
            tx_busy_l2p <= 1'b0;
        end else begin
            tx_busy_l2p <= tx_busy;
        end
    end

    assign tx_done_pulse = ~tx_busy & tx_busy_l2p;

    uart_receiver uart_receiver (
        .clk(i_clk),
        .reset(i_rst),
        .baud_select(3'b111),
        .rx_en(rx_enabled),
        .rxD(i_uart_rx),
        .rx_data(rx_data),
        .rx_ferror(o_ferror),
        .rx_perror(o_perror),
        .rx_valid(rx_valid)
    );

    uart_transmitter uart_transmitter (
        .clk(i_clk),
        .reset(i_rst),
        .baud_select(3'b111),
        .tx_en(tx_enabled),
        .tx_data(tx_data),
        .tx_wr(tx_wr),
        .txD(o_uart_tx),
        .tx_busy(tx_busy)
    );
    
endmodule