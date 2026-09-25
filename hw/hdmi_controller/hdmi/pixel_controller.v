module pixel_controller #(
    parameter UPSCALE_WIDTH = 3,
    parameter UPSCALE_CYCLES = 4
) (
    clk,
    reset,
    write_enable,
    write_address,
    write_data,
    hrgb_enabled,
    vrgb_enabled,
    hpixel,
    hpixel_upscale_counter,
    vpixel,
    r,
    g,
    b
);
    input clk, reset;
    input hrgb_enabled, vrgb_enabled;
    input [6:0] hpixel, vpixel;
    input write_enable;
    input [13:0] write_address;
    input [2:0] write_data;
    input [UPSCALE_WIDTH-1:0] hpixel_upscale_counter;
    output reg r, g, b;

    wire rgb_enabled;
    wire [13:0] current_address;
    wire [15:0] vram_red, vram_green, vram_blue;
    reg [13:0] vram_address;

    assign rgb_enabled = hrgb_enabled & vrgb_enabled;
    assign current_address = {vpixel, hpixel};
    
    vram vram_inst(.clk(clk), .reset(reset), .write_enable(write_enable), .write_address(write_address), .write_data(write_data), .read_address(vram_address), .r(vram_red), .g(vram_green), .b(vram_blue));

    always @(current_address or hpixel_upscale_counter) begin
        if (current_address[3:0] == 4'b1111 && hpixel_upscale_counter == UPSCALE_CYCLES) begin
            vram_address = current_address + 1'b1;
        end else begin
            vram_address = current_address;
        end
    end

    always @(rgb_enabled or vram_red or vram_green or vram_blue or current_address) begin
        if (!rgb_enabled) begin
            r = 1'b0;
            g = 1'b0;
            b = 1'b0;
        end else begin
            r = vram_red[current_address[3:0]];
            g = vram_green[current_address[3:0]];
            b = vram_blue[current_address[3:0]];
        end
    end
    
endmodule