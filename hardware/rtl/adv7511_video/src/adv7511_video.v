`timescale 1ns / 1ps
// RGB video to the 16-bit YCbCr 4:2:2 input of an Analog Devices ADV7511 HDMI
// transmitter, as wired on the ZedBoard (HD_D[15:0], HD_CLK, HD_DE, HD_HSYNC,
// HD_VSYNC).
//
// Input: the parallel video of v_axi4s_vid_out (RGB, 8 bits per component, in
// AXI4-Stream video order {R, B, G}) with its active-video and sync signals,
// all on the pixel clock.
//
// Output: per pixel, Y on hdmi_d[7:0] and one chroma sample on hdmi_d[15:8],
// Cb on the first pixel of every active run, then Cr, Cb, ... (chroma is
// decimated, not filtered). That is the ADV7511's input ID 1 (separate
// syncs), style 1, 8 bits, right-justified, the layout of Analog Devices'
// ZedBoard reference design; the host programs the chip to match
// (software/host/xc7z020/adv7511.c), and the chip's colour space converter
// turns the YCbCr back into RGB for the display.
//
// Colour space: ITU-R BT.709, limited range (Y 16..235, Cb and Cr 16..240),
// matching the YCbCr-to-RGB coefficients the host loads into the ADV7511.
// Coefficients are the BT.709 matrix times 219/255 (Y) or 224/255 (Cb, Cr),
// times 1024 and rounded so each chroma row sums to 0: a grey input gives
// exactly Cb = Cr = 128.
//
// Timing: every output is registered in the I/O block, and the forwarded
// clock is inverted, so the ADV7511 samples on a rising edge in the middle
// of each data bit (half a pixel period of setup and of hold) whatever the
// routing delays are. The data, DE and syncs all go through the same three
// register stages, so they stay aligned.
module adv7511_video (
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 clk CLK" *)
    (* X_INTERFACE_PARAMETER = "ASSOCIATED_RESET reset" *)
    input  wire        clk,
    (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 reset RST" *)
    (* X_INTERFACE_PARAMETER = "POLARITY ACTIVE_HIGH" *)
    input  wire        reset,
    input  wire [23:0] vid_data,
    input  wire        vid_active_video,
    input  wire        vid_hsync,
    input  wire        vid_vsync,
    output wire        hdmi_clk,
    (* IOB = "TRUE" *) output reg [15:0] hdmi_d,
    (* IOB = "TRUE" *) output reg        hdmi_de,
    (* IOB = "TRUE" *) output reg        hdmi_hsync,
    (* IOB = "TRUE" *) output reg        hdmi_vsync
);
    // Stage 1: the components.
    reg [7:0] r, g, b;
    reg       de1, hsync1, vsync1;

    // Stage 2: the weighted sums in Q10, offsets and rounding included. Every
    // sum is positive and below 2^18 for any 8-bit input, so no clipping is
    // needed: Y is 16..235 and Cb, Cr are 16..240 after the shift.
    localparam [17:0] Y_OFFSET = (16 << 10) + 512;
    localparam [17:0] C_OFFSET = (128 << 10) + 512;
    reg [17:0] y_sum, cb_sum, cr_sum;
    reg        de2, hsync2, vsync2;

    // Stage 3: chroma alternates within each active run, starting with Cb.
    reg        send_cr;

    always @(posedge clk) begin
        r <= vid_data[23:16];
        b <= vid_data[15:8];
        g <= vid_data[7:0];
        de1 <= vid_active_video;
        hsync1 <= vid_hsync;
        vsync1 <= vid_vsync;

        y_sum  <= Y_OFFSET + 18'd187 * r + 18'd629 * g + 18'd63 * b;
        cb_sum <= C_OFFSET + 18'd450 * b - 18'd103 * r - 18'd347 * g;
        cr_sum <= C_OFFSET + 18'd450 * r - 18'd409 * g - 18'd41 * b;
        de2 <= de1;
        hsync2 <= hsync1;
        vsync2 <= vsync1;

        if (reset) begin
            hdmi_d <= 16'd0;
            hdmi_de <= 1'b0;
            hdmi_hsync <= 1'b0;
            hdmi_vsync <= 1'b0;
            send_cr <= 1'b0;
        end else begin
            hdmi_d <= de2 ? {send_cr ? cr_sum[17:10] : cb_sum[17:10], y_sum[17:10]} : 16'd0;
            hdmi_de <= de2;
            hdmi_hsync <= hsync2;
            hdmi_vsync <= vsync2;
            send_cr <= de2 & ~send_cr;
        end
    end

    // The pixel clock to the pin through an output DDR register, inverted
    // (low in the first half of each cycle): its rising edge falls in the
    // middle of the data launched on the clock's own rising edge.
    ODDR #(
        .DDR_CLK_EDGE("OPPOSITE_EDGE"),
        .INIT(1'b0),
        .SRTYPE("SYNC")
    ) clock_forward (
        .Q(hdmi_clk),
        .C(clk),
        .CE(1'b1),
        .D1(1'b0),
        .D2(1'b1),
        .R(1'b0),
        .S(1'b0)
    );
endmodule
