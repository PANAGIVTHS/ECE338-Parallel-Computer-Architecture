module uart_transmitter (clk, reset, baud_select, tx_data, tx_en, tx_wr, txD, tx_busy);
    input clk, reset, tx_en, tx_wr;
    input [7:0] tx_data;
    input [2:0] baud_select;
    output wire txD, tx_busy;

    wire [3:0] sample_counter;
    wire enable_sample;
    wire tx_sample;
    assign tx_sample = sample_counter == 4'b1111 && enable_sample == 1'b1;

    baud_controller baud_controller_inst(.clk(clk), .reset(reset), .enable(tx_busy), .baud_select(baud_select), .enable_sample(enable_sample));
    sample_counter sample_counter_inst(.clk(clk), .reset(reset), .enable(tx_busy), .sample_pulse(enable_sample), .sample_counter(sample_counter));
    transmitter_fsm transmitter_fsm_inst(.clk(clk), .reset(reset), .tx_en(tx_en), .tx_wr(tx_wr), .tx_sample(tx_sample), .tx_data(tx_data), .txD(txD), .tx_busy(tx_busy));

endmodule