module baud_controller(input clk, input reset, input enable, input [2:0] baud_select, output wire enable_sample);
    reg [14:0] counter;
    reg [14:0] max_counter;
    parameter max_0 = 15'd20_833; //sfalma 1/3
    parameter max_1 = 15'd5_208; //sfalma 1/3 
    parameter max_2 = 15'd1_302; //sfalma .08333...
    parameter max_3 = 15'd651; //sfalma .04166666...
    parameter max_4 = 15'd326; //sfalma -.479166...
    parameter max_5 = 15'd163; //sfalma -.23958333...
    parameter max_6 = 15'd108; //sfalma -.493055...
    parameter max_7 = 15'd77; //3750 -> 72MHz-1200, 38 -> 72MHz-115200, 54 sfalma .25347222...

    assign enable_sample = max_counter == counter;

    always @(posedge clk) begin
        if (!reset) begin
            counter <= 14'b0;
        end else if (enable) begin
            if (counter == max_counter) begin
                counter <= 14'b0;
            end else begin
                counter <= counter + 14'b1;
            end
        end else begin
            counter <= 14'b0;
        end
    end

    always @(baud_select) begin
        case (baud_select)
            3'b000: max_counter = max_0;
            3'b001: max_counter = max_1;
            3'b010: max_counter = max_2;
            3'b011: max_counter = max_3;
            3'b100: max_counter = max_4;
            3'b101: max_counter = max_5;
            3'b110: max_counter = max_6;
            3'b111: max_counter = max_7;
        endcase
    end

endmodule