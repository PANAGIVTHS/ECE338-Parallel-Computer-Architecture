module DDRWriteRing 
    import DDRBackendPkg::*;
    import MemorySubsystemPkg::*;
    import AXI4FullPkg::*;
#(
    parameter int unsigned NUM_REQ
) (
    input logic clk,
    input logic rst_n,

    // For AXI Channel
    input logic aw_ready,
    input logic w_ready,
    input logic b_valid,
    input axi_resp_t b_resp,
    output logic w_valid,
    output logic w_last,
    output logic wr_owed,
    output cmd_t aw_cmd, // For last accepted group (AW channel)

    // For accepting groups
    output logic free, // AW command register free and a slot is free
    output ring_index_t alloc, // Next free slot
    
    // Formed group
    input logic push_wr, // Push new group into a slot
    input ring_group_t group_address,
    input beat_t first_beat, 
    input beat_t last_beat,

    // Members valid and ready masks, index per member
    input logic [NUM_REQ-1:0] wr_members,
    input ring_index_t[NUM_REQ-1:0] idx,
    input logic [NUM_REQ-1:0] wr_take,

    // For write assembler
    output beat_t w_wbeat, // Beat index of current burst (W channel)
    output ring_index_t w_slot, // Current slot sending its burst (W channel)
    // For DDR interface
    output [NUM_REQ-1:0] wr_bdone, // (B channel)
    output axi_resp_t[NUM_REQ-1:0] wr_bresp, // (B channel)
    
    // State
    output logic busy,
    output logic fatal,
    output mem_fatal_t fatal_code
);

    //& =============================================
    //& AW command register, empties when AW channel 
    //& handshakes and fills when new group is pushed to a slot
    //& =============================================
    beat_t length;
    assign length = last_beat - first_beat;
    always_ff @(posedge clk) begin
        if (~rst_n) begin
            aw_cmd <= '0;
        end else if (push_wr) begin
            aw_cmd <= cmd_t'{
                valid: 1'b1,
                addr: axi_addr_t'(word_of(group_address, first_beat)),
                len: axi_len_t'(length)
            };
        end else if (aw_cmd.valid & aw_ready) begin
            aw_cmd <= '0;
        end
    end

    assign free = ~aw_cmd.valid | aw_ready; // TODO: and it with ring full logic
    
endmodule
