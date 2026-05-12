module receiver_sampler(clk, reset, enable, sample_pulse, data, sample_mid, sample_done, previous_bit, current_bit);
    input clk, reset, enable, sample_pulse, data;
    output reg previous_bit, current_bit;
    output wire sample_mid, sample_done;

    wire [3:0] sample_counter;
    assign sample_mid = sample_counter == 4'd8 && sample_pulse;
    assign sample_done = sample_counter == 4'd15 && sample_pulse;
    sample_counter sample_counter_inst(.clk(clk), .reset(reset), .enable(enable), .sample_pulse(sample_pulse), .sample_counter(sample_counter));

    always @(posedge clk) begin
        if (!reset) begin
            previous_bit <= 1'b0;
        end else if (!enable) begin
            previous_bit <= 1'b0;
        end else if (enable && sample_counter == 4'b0000 && sample_pulse) begin
            previous_bit <= data;
        end else if (enable && sample_counter[0] == 1'b0 && sample_pulse) begin
            previous_bit <= current_bit;
        end
    end

    always @(posedge clk) begin
        if (!reset) begin
            current_bit <= 1'b0;
        end else if (!enable) begin
            current_bit <= 1'b0;
        end else if (enable && sample_counter[0] == 1'b0 && sample_pulse) begin
            current_bit <= data;
        end
    end
    
endmodule