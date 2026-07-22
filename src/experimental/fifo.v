`include "../constants.vh"

module fifo #(
    parameter WIDTH = 32,
    parameter INOUT_RATIO = 4, 
    parameter DEPTH = 8
)(
    input clk,
    input rst,
    
    input i_enqueue,
    input i_dequeue,
    input [(INOUT_RATIO*WIDTH)-1:0] i_data,
    
    output [WIDTH-1:0] o_data,
    output o_empty,
    output reg o_op_dismissed,
    output o_ready_eq,
    output o_full
);

    localparam ROW_COUNT = DEPTH / INOUT_RATIO;
    
    //! ASSERTION
    initial begin
        if (DEPTH < (2 * INOUT_RATIO)) begin
            $display("FATAL ERROR: FIFO DEPTH (%0d) must be >= 2 * INOUT_RATIO (%0d)", DEPTH, INOUT_RATIO);
            $finish;
        end
        if ((INOUT_RATIO & (INOUT_RATIO - 1)) != 0) begin
            $display("FATAL ERROR: FIFO INOUT_RATIO (%0d) must be a power of 2", INOUT_RATIO);
            $finish;
        end
    end

    reg [(INOUT_RATIO*WIDTH)-1:0] fifo_array [0:ROW_COUNT-1];
    reg [$clog2(ROW_COUNT)-1:0] wr_ptr;     
    reg [$clog2(DEPTH)-1:0] rd_ptr;
    reg [$clog2(DEPTH):0] count;

    assign o_empty = (count == 0);
    assign o_full = (count == DEPTH);    
    assign o_ready_eq = (count <= (DEPTH - INOUT_RATIO)) || (i_dequeue && (count == (DEPTH - INOUT_RATIO + 1)));

    //! If you keep INOUT_RATIO power of 2 (/, %) are zero overhead.
    wire [$clog2(ROW_COUNT)-1:0] rd_row_idx = rd_ptr / INOUT_RATIO;
    wire [$clog2(INOUT_RATIO)-1:0] rd_col_idx = rd_ptr % INOUT_RATIO;
    wire [(INOUT_RATIO*WIDTH)-1:0] active_row = fifo_array[rd_row_idx];
    
    reg [WIDTH-1:0] data_out_mux;

    integer i;

    //! Output select
    always @(*) begin
        data_out_mux = {WIDTH{1'b0}};
        for (i = 0; i < INOUT_RATIO; i = i + 1) begin
            if (rd_col_idx == i[$clog2(INOUT_RATIO)-1:0]) begin
                data_out_mux = active_row[(i * WIDTH) +: WIDTH];
            end
        end
    end
    
    //! Be safe and output 0
    assign o_data = (!o_empty) ? data_out_mux : {WIDTH{1'b0}};

    always @(posedge clk or posedge rst) begin
        if (rst) begin
            wr_ptr <= 0;
            rd_ptr <= 0;
            count <= 0;
            o_op_dismissed <= 0;
        end else begin
            o_op_dismissed <= 0; 

            case ({i_enqueue, i_dequeue})                                                
                `FIFO_ENQ_DEQ: begin
                    if (o_ready_eq) begin
                        fifo_array[wr_ptr] <= i_data;

                        rd_ptr <= rd_ptr + 1'b1;
                        wr_ptr <= wr_ptr + 1'b1; 
                        count <= count + INOUT_RATIO - 1'b1;
                    end else begin
                        o_op_dismissed <= 1'b1; 
                    end
                end
                `FIFO_ENQ: begin
                    if (o_ready_eq) begin
                        fifo_array[wr_ptr] <= i_data;
                        
                        wr_ptr <= wr_ptr + 1'b1;
                        count <= count + INOUT_RATIO;
                    end else begin
                        o_op_dismissed <= 1'b1; 
                    end
                end
                `FIFO_DEQ: begin
                    if (count > 0) begin
                        rd_ptr <= rd_ptr + 1'b1;
                        count <= count - 1'b1;
                    end else begin
                        o_op_dismissed <= 1'b1;
                    end
                end
                `FIFO_NOP: begin
                    //! Maintain state
                end
            endcase
        end
    end

endmodule