module ResetDebouncer(input clk, input input_bounce, output reg debounced, output wire debounced_on, output wire debounced_off);
    wire input_1;
    reg input_2;
    reg [15:0] counter;
    wire counter_running;
    assign counter_running = ~(input_1 ^ input_2);
    assign debounced_on = counter_running && counter == 16'h9C40 && debounced;
    assign debounced_off = counter_running && counter == 16'h9C40 && ~debounced;

    ResetSynchronizer sync_inst(.clk(clk), .async_input(input_bounce), .sync_input(input_1));

    always @(posedge clk) begin
        input_2 <= input_1;    
    end

    always @(posedge clk) begin
        if (counter == 16'h9C40) begin
            debounced <= input_2;
        end
        
        if (counter_running) begin
            counter <= counter + 16'b1;
        end else begin
            counter <= 16'b0;
        end
    end

endmodule