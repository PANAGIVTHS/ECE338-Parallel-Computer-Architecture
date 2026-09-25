module renderer (
    clk,
    reset,
    edit_mode,
    up_ctrl,
    down_ctrl,
    left_ctrl,
    right_ctrl,
    frame_end,
    write_enable,
    write_address,
    write_data
);

    parameter WAIT = 1'b0;
    parameter WRITE = 1'b1;
    parameter X_BOUNDARY = 7'd127;
    parameter Y_BOUNDARY = 7'd96;

    input clk, reset;
    input frame_end, edit_mode;
    input up_ctrl, down_ctrl, left_ctrl, right_ctrl;
    output reg [13:0] write_address;
    output reg [2:0] write_data;
    output reg write_enable;

    reg current_state, next_state;
    reg [13:0] sprite_read_address;
    wire [13:0] start_pos, end_pos;
    wire sprite_out;
    wire r, g, b;

    sprite_vram sprite_vram_inst(.clk(clk), .reset(reset), .read_address(sprite_read_address), .out(sprite_out));
    sprite_controller #(
        .X_BOUNDARY(X_BOUNDARY),
        .Y_BOUNDARY(Y_BOUNDARY)
    ) sprite_controller_inst(.clk(clk), .reset(reset), .edit_mode(edit_mode), .frame_end(frame_end),
    .up_ctrl(up_ctrl), .down_ctrl(down_ctrl), .left_ctrl(left_ctrl), .right_ctrl(right_ctrl),
    .start_pos(start_pos), .end_pos(end_pos), .r(r), .g(g), .b(b));

    always @(write_enable or write_address or start_pos or end_pos) begin
        if (!write_enable) begin
            sprite_read_address = 14'd0;
        end else if (write_address >= start_pos && write_address <= end_pos) begin
            sprite_read_address = write_address - start_pos + 14'b1;
        end else begin 
            sprite_read_address = 14'd0;
        end
    end

    always @(write_enable or write_address or sprite_out or r or g or b or start_pos or end_pos) begin
        if (!write_enable) begin
            write_data = 3'b0;
        end else if (write_address >= start_pos && write_address <= end_pos) begin
            write_data = sprite_out ? {r, g, b} : 3'b0;        
        end else begin
            write_data = 3'b0;
        end
    end

    always @(posedge clk) begin
        if (reset) begin
            write_address <= 14'b0;
        end else if (!write_enable) begin
            write_address <= 14'b0;
        end else begin
            write_address <= write_address + 14'b1;
        end
    end

    always @(posedge clk) begin
        if (reset) begin
            current_state <= WRITE;
        end else begin
            current_state <= next_state;
        end
    end

    always @(current_state or write_address or frame_end) begin
        case (current_state)
            WAIT: next_state = frame_end ? WRITE : WAIT;
            WRITE: next_state = write_address == 14'd11_775 ? WAIT : WRITE; 
            default: next_state = WAIT; 
        endcase
    end

    always @(current_state) begin
        case (current_state)
            WAIT: write_enable = 1'b0;
            WRITE: write_enable = 1'b1;
            default: write_enable = 1'b0; 
        endcase
    end

    
endmodule