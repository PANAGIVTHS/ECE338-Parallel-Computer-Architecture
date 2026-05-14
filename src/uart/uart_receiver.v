module uart_receiver(clk, reset, baud_select, rx_en, rxD, rx_data, rx_ferror, rx_perror, rx_valid);
    input clk, reset, rx_en, rxD;
    input [2:0] baud_select;
    output wire [7:0] rx_data;
    output wire rx_valid, rx_ferror, rx_perror;

    wire rx_busy, rx_busy_data;
    wire rx_sample, sample_mid, sample_done, previous_bit, current_bit;
    wire sample_diff;
    assign sample_diff = previous_bit != current_bit;
    
    reg rxD_sync1;
    reg rxD_safe;

    always @(posedge clk) begin
        if (!reset) begin
            rxD_sync1 <= 1'b1;
            rxD_safe  <= 1'b1;
        end else begin
            rxD_sync1 <= rxD;
            rxD_safe  <= rxD_sync1;
        end
    end

    baud_controller baud_controller_inst(.clk(clk), .reset(reset), .enable(rx_busy), .baud_select(baud_select), .enable_sample(rx_sample));
    
    receiver_sampler receiver_sampler_inst(.clk(clk), .reset(reset), .enable(rx_busy), .sample_pulse(rx_sample),
    .data(rxD_safe), .sample_mid(sample_mid), .sample_done(sample_done), .previous_bit(previous_bit), .current_bit(current_bit));
    
    receiver_fsm receiver_fsm_inst(.clk(clk), .reset(reset), .rx_en(rx_en), .rxD(rxD_safe), .sample_mid(sample_mid), .sample_done(sample_done), .sample_diff(sample_diff), .rx_data(rx_data),
    .rx_busy(rx_busy), .rx_busy_data(rx_busy_data), .rx_ferror(rx_ferror), .rx_perror(rx_perror), .rx_valid(rx_valid));
    
    receiver_data receiver_data_inst(.clk(clk), .reset(reset), .sample_mid(sample_mid), .rxD(rxD_safe), .rx_busy_data(rx_busy_data), .rx_data(rx_data));
    
endmodule