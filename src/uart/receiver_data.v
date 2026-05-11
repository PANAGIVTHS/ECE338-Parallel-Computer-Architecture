module receiver_data(clk, reset, sample_mid, rxD, rx_busy_data, rx_data);
    input clk, reset, sample_mid, rxD, rx_busy_data;
    output reg [7:0] rx_data;

    always @(posedge clk or posedge reset) begin
        if (reset) begin
            rx_data <= 8'b00000000;
        end else if (rx_busy_data && sample_mid) begin
            rx_data <= {rxD, rx_data[7:1]};
        end
    end
    
endmodule