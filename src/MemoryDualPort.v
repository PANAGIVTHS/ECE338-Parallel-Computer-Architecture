/*
    True dual port memory to be implemented in vivado's BRAM. A write on the same
    memory address on the same cycle will result in an undefined behaviour.
*/
module MemoryDualPort #(
    parameter DEPTH = 1024,
    parameter INIT_FILE = ""
)(
    input clk,

    //! Port A
    input [$clog2(DEPTH)-1:0] i_addr_a,
    input i_ren_a,
    input i_wen_a,
    input [31:0] i_data_a,
    output reg [31:0] o_out_a,

    //! Port B
    input [$clog2(DEPTH)-1:0] i_addr_b,
    input i_ren_b,
    input i_wen_b,
    input [31:0] i_data_b,
    output reg [31:0] o_out_b
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

    //! Port B
    always @(posedge clk) begin
        if (i_wen_b) begin
            data[i_addr_b] <= i_data_b;
        end

        if (i_ren_b) begin
            if (i_wen_b) begin
                o_out_b <= i_data_b;
            end else begin
                o_out_b <= data[i_addr_b];
            end
        end
    end

endmodule
