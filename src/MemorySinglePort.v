module MemorySinglePort #(
    parameter DEPTH = 1024,
    parameter INIT_FILE = ""
)(
    input clk,
    input [$clog2(DEPTH)-1:0] i_addr_a,
    input i_ren_a,
    input i_wen_a,
    input [31:0] i_data_a,
    output reg [31:0] o_out_a
);

    (* ram_style = "block" *) reg [31:0] data [0:DEPTH-1];

    initial begin
        if (INIT_FILE != "") begin
            $readmemh(INIT_FILE, data);
        end
    end

    //! Port A
    always @(posedge clk) begin
        if (i_wen_a) begin
            data[i_addr_a] <= i_data_a;
        end

        if (i_ren_a) begin
            if (i_wen_a) begin
                o_out_a <= i_data_a;
            end else begin
                o_out_a <= data[i_addr_a];
            end
        end
    end
endmodule
