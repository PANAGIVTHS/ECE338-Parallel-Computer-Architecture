module receiver_fsm(clk, reset, rx_en, rxD, sample_mid, sample_done, sample_diff, rx_data, rx_busy, rx_busy_data, rx_ferror, rx_perror, rx_valid);
    input clk, reset, rx_en, rxD, sample_mid, sample_done, sample_diff;
    input [7:0] rx_data;
    output reg rx_busy, rx_busy_data, rx_ferror, rx_perror, rx_valid;

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
    localparam COMPLETED = 4'd13;
    localparam PERROR = 4'd14;
    localparam FERROR = 4'd15;

    always @(posedge clk) begin
        if (!reset) begin
            current_state <= DISABLED;
        end else begin
            current_state <= next_state;
        end
    end

    always @(current_state or rx_en or rxD or sample_mid or sample_done or sample_diff or rx_data) begin
        case (current_state)
            DISABLED: begin
                next_state = rx_en ? IDLE : DISABLED;
            end
            IDLE: begin
                if (!rx_en) begin
                    next_state = DISABLED;
                end else if (!rxD) begin
                    next_state = START_BIT;
                end else begin
                    next_state = IDLE;
                end
            end
            COMPLETED: begin
                if (!rx_en) begin
                    next_state = DISABLED;
                end else if (!rxD) begin
                    next_state = START_BIT;
                end else begin
                    next_state = COMPLETED;
                end
            end
            START_BIT: begin
                if (sample_diff) begin
                    next_state = FERROR;
                end else begin
                    next_state = sample_done ? BIT_0 : START_BIT;
                end 
            end
            BIT_0: begin
                if (sample_diff) begin
                    next_state = FERROR;
                end else begin
                    next_state = sample_done ? BIT_1 : BIT_0;
                end 
            end
            BIT_1: begin
                if (sample_diff) begin
                    next_state = FERROR;
                end else begin
                    next_state = sample_done ? BIT_2 : BIT_1;
                end 
            end
            BIT_2: begin
                if (sample_diff) begin
                    next_state = FERROR;
                end else begin
                    next_state = sample_done ? BIT_3 : BIT_2;
                end 
            end
            BIT_3: begin
                if (sample_diff) begin
                    next_state = FERROR;
                end else begin
                    next_state = sample_done ? BIT_4 : BIT_3;
                end 
            end
            BIT_4: begin
                if (sample_diff) begin
                    next_state = FERROR;
                end else begin
                    next_state = sample_done ? BIT_5 : BIT_4;
                end 
            end
            BIT_5: begin
                if (sample_diff) begin
                    next_state = FERROR;
                end else begin
                    next_state = sample_done ? BIT_6 : BIT_5;
                end 
            end
            BIT_6: begin
                if (sample_diff) begin
                    next_state = FERROR;
                end else begin
                    next_state = sample_done ? BIT_7 : BIT_6;
                end 
            end
            BIT_7: begin
                if (sample_diff) begin
                    next_state = FERROR;
                end else begin
                    next_state = sample_done ? STOP_BIT : BIT_7;
                end
            end
            PARITY_BIT: begin
                if (sample_diff) begin
                    next_state = FERROR;
                end else if (sample_mid && ^rx_data ^^ rxD) begin
                    next_state = PERROR;
                end else begin
                    next_state = sample_done ? STOP_BIT : PARITY_BIT;
                end
            end
            STOP_BIT: begin
                if (sample_diff) begin
                    next_state = FERROR;
                end else begin
                    next_state = sample_done ? COMPLETED : STOP_BIT;
                end
            end
            PERROR: begin
                next_state = ~rx_en ? DISABLED : PERROR;
            end
            FERROR: begin
                next_state = ~rx_en ? DISABLED : FERROR;
            end
            default: begin
                next_state = DISABLED;
            end
        endcase
    end

    always @(current_state) begin
        case (current_state)
            DISABLED: begin
                rx_valid = 1'b0;
                rx_ferror = 1'b0;
                rx_perror = 1'b0;
                rx_busy = 1'b0;
                rx_busy_data = 1'b0;
            end
            IDLE: begin
                rx_valid = 1'b0;
                rx_ferror = 1'b0;
                rx_perror = 1'b0;
                rx_busy = 1'b0;
                rx_busy_data = 1'b0;
            end
            COMPLETED: begin
                rx_valid = 1'b1;
                rx_ferror = 1'b0;
                rx_perror = 1'b0;
                rx_busy = 1'b0;
                rx_busy_data = 1'b0;
            end
            START_BIT: begin
                rx_valid = 1'b0;
                rx_ferror = 1'b0;
                rx_perror = 1'b0;
                rx_busy = 1'b1;
                rx_busy_data = 1'b0;
            end
            BIT_0: begin
                rx_valid = 1'b0;
                rx_ferror = 1'b0;
                rx_perror = 1'b0;
                rx_busy = 1'b1;
                rx_busy_data = 1'b1;
            end
            BIT_1: begin
                rx_valid = 1'b0;
                rx_ferror = 1'b0;
                rx_perror = 1'b0;
                rx_busy = 1'b1;
                rx_busy_data = 1'b1;
            end
            BIT_2: begin
                rx_valid = 1'b0;
                rx_ferror = 1'b0;
                rx_perror = 1'b0;
                rx_busy = 1'b1;
                rx_busy_data = 1'b1;
            end
            BIT_3: begin
                rx_valid = 1'b0;
                rx_ferror = 1'b0;
                rx_perror = 1'b0;
                rx_busy = 1'b1;
                rx_busy_data = 1'b1;
            end
            BIT_4: begin
                rx_valid = 1'b0;
                rx_ferror = 1'b0;
                rx_perror = 1'b0;
                rx_busy = 1'b1;
                rx_busy_data = 1'b1;
            end
            BIT_5: begin
                rx_valid = 1'b0;
                rx_ferror = 1'b0;
                rx_perror = 1'b0;
                rx_busy = 1'b1;
                rx_busy_data = 1'b1;
            end
            BIT_6: begin
                rx_valid = 1'b0;
                rx_ferror = 1'b0;
                rx_perror = 1'b0;
                rx_busy = 1'b1;
                rx_busy_data = 1'b1;
            end
            BIT_7: begin
                rx_valid = 1'b0;
                rx_ferror = 1'b0;
                rx_perror = 1'b0;
                rx_busy = 1'b1;
                rx_busy_data = 1'b1;
            end
            PARITY_BIT: begin
                rx_valid = 1'b0;
                rx_ferror = 1'b0;
                rx_perror = 1'b0;
                rx_busy = 1'b1;
                rx_busy_data = 1'b0;
            end
            STOP_BIT: begin
                rx_valid = 1'b0;
                rx_ferror = 1'b0;
                rx_perror = 1'b0;
                rx_busy = 1'b1;
                rx_busy_data = 1'b0;
            end
            PERROR: begin
                rx_valid = 1'b0;
                rx_ferror = 1'b0;
                rx_perror = 1'b1;
                rx_busy = 1'b0;
                rx_busy_data = 1'b0;
            end
            FERROR: begin
                rx_valid = 1'b0;
                rx_ferror = 1'b1;
                rx_perror = 1'b0;
                rx_busy = 1'b0;
                rx_busy_data = 1'b0;
            end
            default: begin
                rx_valid = 1'b0;
                rx_ferror = 1'b0;
                rx_perror = 1'b0;
                rx_busy = 1'b0;
                rx_busy_data = 1'b0;
            end
        endcase
    end
    
endmodule