module ResetSynchronizer(input clk, input async_input, output reg sync_input);
    reg input_prime;

    always @(posedge clk)
    begin
        input_prime <= async_input;
    end

    always @(posedge clk)
    begin
        sync_input <= input_prime;
    end
    
endmodule