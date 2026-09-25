module tmds_encoder(
    input clk, 
    input rst, 
    input [7:0] data_in,
    input [1:0] control_in, 
    input ve_in,
    output reg [9:0] tmds_out
);
    reg signed [4:0] x_s;
    wire [8:0] m_v;
    wire [3:0] n_1;
    
    assign n_1 = data_in[0]+data_in[1]+data_in[2]+data_in[3]+data_in[4]+data_in[5]+data_in[6]+data_in[7];
    assign m_v[0] = data_in[0];
    generate 
        genvar j;
        for(j=1; j<8; j=j+1) begin : bit_gen
            assign m_v[j] = ((n_1 > 4) || (n_1 == 4 && !data_in[0])) ? ~(m_v[j-1] ^ data_in[j]) : (m_v[j-1] ^ data_in[j]);
        end
    endgenerate
    assign m_v[8] = (n_1 > 4) || (n_1 == 4 && !data_in[0]) ? 1'b0 : 1'b1;

    wire [3:0] c_1 = m_v[0]+m_v[1]+m_v[2]+m_v[3]+m_v[4]+m_v[5]+m_v[6]+m_v[7];
    wire [4:0] d_v = {1'b0, c_1} - (5'd8 - {1'b0, c_1});
    
    always @(posedge clk or posedge rst) begin
        if (rst) begin
            x_s <= 5'sh0;
            tmds_out <= 10'h0;
        end else if (!ve_in) begin
            x_s <= 5'sh0;
            tmds_out <= (control_in[1]) ? (control_in[0] ? 10'b1010101011 : 10'b0101010100) : 
                                         (control_in[0] ? 10'b0010101011 : 10'b1101010100);
        end else begin
            if (x_s == 0 || (c_1 == 4'd4)) begin
                tmds_out <= {~m_v[8], m_v[8], (m_v[8] ? m_v[7:0] : ~m_v[7:0])};
                x_s <= x_s + (m_v[8] ? d_v : -d_v);
            end else begin
                if ((!x_s[4] && (c_1 > 4)) || (x_s[4] && (c_1 < 4))) begin
                    tmds_out <= {1'b1, m_v[8], ~m_v[7:0]};
                    x_s <= x_s + {m_v[8], 1'b0} - d_v;
                end else begin
                    tmds_out <= {1'b0, m_v[8], m_v[7:0]};
                    x_s <= x_s - {~m_v[8], 1'b0} + d_v;
                end
            end
        end
    end
endmodule