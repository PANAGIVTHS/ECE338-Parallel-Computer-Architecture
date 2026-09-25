module InputDebouncer(input clk, input reset, input input_bounce, output reg debounced, output reg posedge_pulse);
    wire input_1;
    reg input_2, last_state;
    reg [15:0] counter;
    wire counter_running;
    assign counter_running = input_1 && input_2;

    InputSynchronizer sync_inst(.clk(clk), .reset(reset), .async_input(input_bounce), .sync_input(input_1));

    always @(posedge clk or posedge reset) begin
        if (reset == 1'b1)
            input_2 <= 1'b0;    
        else 
            input_2 <= input_1;
    end

    always @(posedge clk or posedge reset) begin
        if (reset == 1'b1 || !counter_running) begin
            debounced <= 1'b0;
            last_state <= 1'b0;
        end else if (counter == 16'h9C40) begin
            debounced <= input_2;
            last_state <= debounced;
        end
    end

    always @(posedge clk or posedge reset) begin
        if (reset == 1'b1 || !counter_running) begin
            counter <= 16'b0;
        end else begin
            counter <= counter + 16'b1;
        end
    end

    always @(debounced or last_state or counter or counter_running) begin
        if (!counter_running) begin
            posedge_pulse = 1'b0;
        end else if (debounced == 1'b1 && last_state == 1'b0 && counter == 16'h0) begin
            posedge_pulse = 1'b1;
        end else begin
            posedge_pulse = 1'b0;
        end
    end

endmodule