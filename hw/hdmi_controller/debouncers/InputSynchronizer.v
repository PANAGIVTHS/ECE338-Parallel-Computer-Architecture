module InputSynchronizer(input clk, input reset, input async_input, output reg sync_input);
    reg input_prime;

    always @(posedge clk or posedge reset)
    begin
        if (reset == 1'b1)
            input_prime <= 1'b0;
        else
            input_prime <= async_input;
    end

    always @(posedge clk or posedge reset)
    begin
        if (reset == 1'b1)
            sync_input <= 1'b0;
        else 
            sync_input <= input_prime;
    end
    
endmodule