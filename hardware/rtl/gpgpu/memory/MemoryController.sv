`include "constants.svh"

module MemoryController #(
    .SP_PER_SM(SP_PER_SM)
) (
    input logic clk,
    output logic o_stall,
    MemoryInterface.slave memory
);

    //& ===============
    //& READ DATA LATCHING
    //& ===============
    reg [31:0] latched_rdata [0:NUM_CORES-1];
    reg [NUM_CORES-1:0] mem_grant_delayed;
    wire [NUM_CORES*32-1:0] flat_mem_rdata;
    integer k;

    //! BRAM data arrives exactly 1 cycle after a grant. We delay the grant signal
    //! to know exactly when to latch the valid data from the crossbar.
    always @(posedge clk) begin
        if (!rst) mem_grant_delayed <= {NUM_CORES{1'b0}};
        //! Only delay the grant signal if it belongs to a valid READ request
        else mem_grant_delayed <= sp_mem_grant & (sp_mem_ren & ~sp_mem_wen);
    end

    always @(posedge clk) begin
        if (!rst) begin
            for (k = 0; k < NUM_CORES; k = k + 1) begin 
                latched_rdata[k] <= 32'b0;
            end
        end else begin
            for (k = 0; k < NUM_CORES; k = k + 1) begin
                if (mem_grant_delayed[k]) begin
                    latched_rdata[k] <= flat_mem_rdata[k*32 +: 32];
                end
            end
        end
    end

    //& ===============
    //& CROSSBAR & STALL LOGIC
    //& ===============
    wire [`DMEM_AW-1:0] sp_mem_addr [0:NUM_CORES-1];
    wire [31:0] sp_mem_wdata [0:NUM_CORES-1];
    wire [NUM_CORES-1:0] sp_mem_ren;
    wire [NUM_CORES-1:0] sp_mem_wen;
    wire [31:0] sp_mem_rdata [0:NUM_CORES-1];
    wire [NUM_CORES-1:0] sp_mem_grant;
    wire [NUM_CORES-1:0] sp_mem_rvalid;
    reg [NUM_CORES-1:0] mem_satisfied;

    //! Only request memory if the core hasn't already been served during this stall
    wire [NUM_CORES-1:0] active_mem_ren = sp_mem_ren & ~mem_satisfied;
    wire [NUM_CORES-1:0] active_mem_wen = sp_mem_wen & ~mem_satisfied;

    //! If even a single core asks for memory but is denied, stall (Handles Reads and Writes)
    wire stall = (|(active_mem_ren & ~sp_mem_grant) | |(active_mem_wen & ~sp_mem_grant)) || !i_enable;
    
    always @(posedge clk) begin
        if (!rst) begin
            mem_satisfied <= {NUM_CORES{1'b0}};
        end else if (!stall) begin
            //! Reset when pipeline moves
            mem_satisfied <= {NUM_CORES{1'b0}};
        end else begin
            //! Accumulate grants
            mem_satisfied <= mem_satisfied | sp_mem_grant;
        end
    end

    //& ===============
    //& GLOBAL DATA MEMORY CROSSBAR
    //& ===============

    wire [NUM_CORES*`DMEM_AW-1:0] flat_mem_addr;
    wire [NUM_CORES*32-1:0] flat_mem_wdata;

    genvar i;
    generate
        for (i = 0; i < NUM_CORES; i = i + 1) begin : gen_flat
            assign flat_mem_addr[i*`DMEM_AW +: `DMEM_AW] = sp_mem_addr[i];
            assign flat_mem_wdata[i*32 +: 32] = sp_mem_wdata[i];
            
            //! If granted exactly 1 cycle ago, read live directly from crossbar
            //! Otherwise (stalled for >1 cycle), read from the safety latch.
            assign sp_mem_rdata[i] = mem_grant_delayed[i] ? flat_mem_rdata[i*32 +: 32] : latched_rdata[i];
        end
    endgenerate

    MemoryCrossbarNx2 #(
        .N(NUM_CORES),
        .DEPTH(`DMEM_ENTRIES),
        .ADDR_W(`DMEM_AW)
    ) memCrossbar (
        .clk(clk),
        .rst(rst),
        // Cores Interface
        .i_req   ( active_mem_ren ), 
        .i_wen   ( active_mem_wen ), 
        .i_addr  ( flat_mem_addr ),
        .i_wdata ( flat_mem_wdata ),
        .o_grant ( sp_mem_grant ),
        .o_rvalid( sp_mem_rvalid ),
        .o_rdata ( flat_mem_rdata ),
        
        // Memory Port A Interface
        .o_addr_a(o_dmem_addr_a),
        .o_ren_a(o_dmem_ren_a),
        .o_wen_a(o_dmem_wen_a),
        .o_data_a(o_dmem_wdata_a),
        .i_out_a(i_dmem_rdata_a),
        
        // Memory Port B Interface
        .o_addr_b(o_dmem_addr_b),
        .o_ren_b(o_dmem_ren_b),
        .o_wen_b(o_dmem_wen_b),
        .o_data_b(o_dmem_wdata_b),
        .i_out_b(i_dmem_rdata_b)
    );

endmodule
