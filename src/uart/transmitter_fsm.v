module transmitter_fsm(clk, reset, tx_en, tx_wr, tx_sample, tx_data, txD, tx_busy);
    input clk, reset, tx_en, tx_wr, tx_sample;
    input [7:0] tx_data;
    output reg txD, tx_busy;

    reg [3:0] current_state, next_state;

    localparam DISABLED = 4'd0;
    localparam IDLE = 4'd1;
    localparam START_BIT = 4'd2;
    localparam BIT_0 = 4'd3;
    localparam BIT_1 = 4'd4;
    localparam BIT_2 = 4'd5;
    localparam BIT_3 = 4'd6;
    localparam BIT_4 = 4'd7;
    localparam BIT_5 = 4'd8;
    localparam BIT_6 = 4'd9;
    localparam BIT_7 = 4'd10;
    localparam PARITY_BIT = 4'd11;
    localparam STOP_BIT = 4'd12;

    always @(posedge clk) begin
        if (!reset) begin
            current_state <= DISABLED;
        end else begin
            current_state <= next_state;
        end
    end

    always @(current_state or tx_en or tx_wr or tx_sample) begin
        case (current_state)
            DISABLED: begin
                next_state = tx_en ? IDLE : DISABLED;
            end
            IDLE: begin
                if (!tx_en) begin
                    next_state = DISABLED;
                end else if (tx_wr) begin
                    next_state = START_BIT;
                end else begin
                    next_state = IDLE;
                end
            end
            START_BIT: begin
                next_state = tx_sample ? BIT_0 : START_BIT;
            end
            BIT_0: begin
                next_state = tx_sample ? BIT_1 : BIT_0;
            end
            BIT_1: begin
                next_state = tx_sample ? BIT_2 : BIT_1;
            end
            BIT_2: begin
                next_state = tx_sample ? BIT_3 : BIT_2;
            end
            BIT_3: begin
                next_state = tx_sample ? BIT_4 : BIT_3;
            end
            BIT_4: begin
                next_state = tx_sample ? BIT_5 : BIT_4;
            end
            BIT_5: begin
                next_state = tx_sample ? BIT_6 : BIT_5;
            end
            BIT_6: begin
                next_state = tx_sample ? BIT_7 : BIT_6;
            end
            BIT_7: begin
                next_state = tx_sample ? STOP_BIT : BIT_7;
            end
            PARITY_BIT: begin
                next_state = tx_sample ? STOP_BIT : PARITY_BIT;
            end
            STOP_BIT: begin
                next_state = tx_sample ? IDLE : STOP_BIT;
            end
            default: begin
                next_state = DISABLED;
            end
        endcase
    end
    
    always @(current_state or tx_data) begin
        case (current_state)
            DISABLED: begin
                txD = 1'b1;
                tx_busy = 1'b0;
            end
            IDLE: begin
                txD = 1'b1;
                tx_busy = 1'b0;
            end
            START_BIT: begin
                txD = 1'b0;
                tx_busy = 1'b1;
            end
            BIT_0: begin
                txD = tx_data[0];
                tx_busy = 1'b1;
            end
            BIT_1: begin
                txD = tx_data[1];
                tx_busy = 1'b1;
            end
            BIT_2: begin
                txD = tx_data[2];
                tx_busy = 1'b1;
            end
            BIT_3: begin
                txD = tx_data[3];
                tx_busy = 1'b1;
            end
            BIT_4: begin
                txD = tx_data[4];
                tx_busy = 1'b1;
            end
            BIT_5: begin
                txD = tx_data[5];
                tx_busy = 1'b1;
            end
            BIT_6: begin
                txD = tx_data[6];
                tx_busy = 1'b1;
            end
            BIT_7: begin
                txD = tx_data[7];
                tx_busy = 1'b1;
            end
            PARITY_BIT: begin
                txD = ^tx_data;
                tx_busy = 1'b1;
            end
            STOP_BIT: begin
                txD = 1'b1;
                tx_busy = 1'b1;
            end
            default: begin
                txD = 1'b0;
                tx_busy = 1'b1;
            end
        endcase
    end

endmodule