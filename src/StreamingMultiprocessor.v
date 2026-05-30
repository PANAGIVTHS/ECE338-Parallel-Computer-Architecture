`include "constants.vh"

module StreamingMultiprocessor #(
    parameter NUM_CORES = 32
) (
    input clk,
    input rst,
    input i_enable,

    input [31:0] i_ifid_instruction,
    output [`IMEM_AW-1:0] o_imem_addr,
    output o_imem_ren,

    input [31:0] i_dmem_rdata_a, i_dmem_rdata_b,
    output [`DMEM_AW-1:0] o_dmem_addr_a, o_dmem_addr_b,
    output [31:0] o_dmem_wdata_a, o_dmem_wdata_b,
    output o_dmem_ren_a, o_dmem_ren_b,
    output o_dmem_wen_a, o_dmem_wen_b,
    
    output o_kernel_complete
);
    wire ex_branch_taken;
    wire [$clog2(`IMEM_ENTRIES)-1:0] ex_beq_target_idx;
    wire data_hazard, flush;
    reg [4:0] idex_rd;

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
    
    always @(posedge clk) begin
        if (!rst) begin
            mem_satisfied <= {NUM_CORES{1'b0}};
        end else if (!global_stall) begin
            //! Reset when pipeline moves
            mem_satisfied <= {NUM_CORES{1'b0}};
        end else begin
            //! Accumulate grants
            mem_satisfied <= mem_satisfied | sp_mem_grant;
        end
    end

    //! Only request memory if the core hasn't already been served during this stall
    wire [NUM_CORES-1:0] active_mem_ren = sp_mem_ren & ~mem_satisfied;
    wire [NUM_CORES-1:0] active_mem_wen = sp_mem_wen & ~mem_satisfied;

    //! If even a single core asks for memory but is denied, stall (Handles Reads and Writes)
    wire global_stall = (|(active_mem_ren & ~sp_mem_grant) | |(active_mem_wen & ~sp_mem_grant)) || !i_enable;

    //& ===============
    //& READ DATA LATCHING
    //& ===============
    reg [31:0] latched_rdata [0:NUM_CORES-1];
    reg [NUM_CORES-1:0] mem_grant_delayed;
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

    //! =========================================================================
    //! STAGE 1: INSTRUCTION FETCH
    //! =========================================================================
    (* dont_touch = `DEBUG *) wire [$clog2(`IMEM_ENTRIES)+1:0] program_counter;
    wire [$clog2(`IMEM_ENTRIES)-1:0] instr_idx;

    (* dont_touch = `DEBUG *)
    GUCounter #(.BITS($clog2(`IMEM_ENTRIES))) 
        programCounter (.clk(clk), .i_set_reset({rst, ex_branch_taken}), .i_count_enable(!data_hazard && !global_stall), .i_count_set(ex_beq_target_idx + 1'b1), .o_count_cur(instr_idx));

    assign program_counter = {instr_idx, 2'b00};
    assign o_imem_ren = (!data_hazard && !global_stall) | flush;
    assign o_imem_addr = flush ? ex_beq_target_idx : instr_idx;

    //* =========================================================================
    //* PIPELINE REGISTER 1: INSTRUCTION FETCH -> INSTRUCTION DECODE
    //* =========================================================================
    reg [$clog2(`IMEM_ENTRIES)+1:0] ifid_program_counter;
    always @(posedge clk) begin
        if (!rst) begin
            ifid_program_counter <= `INITIAL_PC;
        end else if (global_stall) begin
            // Retain state during memory stall
        end else if (flush) begin 
            ifid_program_counter <= {ex_beq_target_idx, 2'b00};
        end else if (!data_hazard) begin
            ifid_program_counter <= program_counter;
        end
    end

    //! =========================================================================
    //! STAGE 2: INSTRUCTION DECODE
    //! =========================================================================
    wire [19:0] id_imm_31_12;
    wire [6:0] id_imm_31_25, id_opcode;
    wire [11:0] id_imm_31_20;
    wire [3:0] id_aluop;
    wire [2:0] id_funct3;
    wire [1:0] id_instr_type;
    wire [4:0] id_rs1, id_rs2, id_rd;
    wire [4:0] id_mux_rs1, id_mux_rs2;
    wire id_is_mul, id_wen;
    reg decode_enabled;

    always @(posedge clk) begin
        if (!rst) begin
            decode_enabled <= 1'b0;
        end else begin
            decode_enabled <= i_enable;
        end
    end

    (* dont_touch = `DEBUG *)
    Decoder decoder (
        .i_instr(i_ifid_instruction),
        .o_rs1(id_rs1), 
        .o_rs2(id_rs2),
        .o_rd(id_rd),
        .o_imm_31_12(id_imm_31_12),
        .o_imm_31_25(id_imm_31_25),
        .o_imm_31_20(id_imm_31_20),
        .o_funct3(id_funct3),
        .o_aluop(id_aluop),
        .o_instr_type(id_instr_type),
        .opcode(id_opcode)
    );

    assign id_wen = (id_rd == 5'b0) ? 1'b0 : (id_opcode == `OP_SW || id_opcode == `OP_BEQ) ? 1'b0 : 1'b1;
    assign id_is_mul = (id_opcode == `OP_R_TYPE) && (id_imm_31_25 == `FUNCT7_MULDIV);

    assign id_mux_rs1 = id_rs1;
    assign id_mux_rs2 = id_rs2;

    //* =========================================================================
    //* PIPELINE REGISTER 2: INSTRUCTION DECODE -> EXECUTE (Feeds into SP)
    //* =========================================================================
    reg [4:0] idex_rs1, idex_rs2;
    reg [19:0] idex_imm_31_12;
    reg [11:0] idex_imm_31_20;
    reg [3:0] idex_aluop;
    reg [2:0] idex_funct3;
    reg [1:0] idex_instr_type;
    reg [6:0] idex_opcode, idex_imm_31_25;
    reg [$clog2(`IMEM_ENTRIES)+1:0] idex_program_counter;
    reg idex_wen;

    always @(posedge clk) begin
        if (!rst) begin
            idex_rs1 <= 5'b0;
            idex_rs2 <= 5'b0;
            idex_rd <= 5'b0;
            idex_imm_31_12 <= 20'b0;
            idex_imm_31_20 <= 12'b0;
            idex_aluop <= 2'b0;
            idex_funct3 <= 3'b0;
            idex_instr_type <= 2'b0;
            idex_opcode <= 7'b0;
            idex_imm_31_25 <= 7'b0;
            idex_program_counter <= `INITIAL_PC;
            idex_wen <= 1'b0;
        end else if (global_stall) begin
            // Retain state during memory stall
        end else if (!decode_enabled || data_hazard) begin
            idex_rs1 <= 5'b0;
            idex_rs2 <= 5'b0;
            idex_rd <= 5'b0;
            idex_imm_31_12 <= 20'b0;
            idex_imm_31_20 <= 12'b0;
            idex_aluop <= `ALU_INVALID;
            idex_funct3 <= 3'b0;
            idex_instr_type <= `INSTR_TYPE_R;
            idex_opcode <= 7'b0;
            idex_imm_31_25 <= 7'b0;
            idex_program_counter <= ifid_program_counter;
            idex_wen <= 1'b0;
        end else begin
            idex_rs1 <= id_rs1;
            idex_rs2 <= id_rs2;
            idex_rd <= id_rd;
            idex_imm_31_12 <= id_imm_31_12;
            idex_imm_31_20 <= id_imm_31_20;
            idex_imm_31_25 <= id_imm_31_25;
            idex_aluop <= id_aluop;
            idex_funct3 <= id_funct3;
            idex_instr_type <= id_instr_type;
            idex_opcode <= id_opcode;
            idex_program_counter <= ifid_program_counter;
            idex_wen <= id_wen;
        end
    end

    //& ===============
    //& HAZARD DETECTION
    //& ===============
    wire mul1_valid, mul2_valid, mul3_valid;
    wire [4:0] mul1_rd, mul2_rd, mul3_rd;
    wire sm_ex_is_load = (idex_opcode == `OP_LW && idex_instr_type == `INSTR_TYPE_I);
    wire sm_ex_is_mul = (idex_opcode == `OP_R_TYPE) && (idex_imm_31_25 == `FUNCT7_MULDIV);

    (* dont_touch = `DEBUG *)
    HazardUnit hazardUnit (
        .i_id_rs1(id_rs1),
        .i_id_rs2(id_rs2),
        .i_idex_rd(idex_rd),
        .i_ex_is_load(sm_ex_is_load),
        .i_ex_is_mul(sm_ex_is_mul),
        .i_id_is_mul(id_is_mul),
        .i_mul1_valid(mul1_valid),
        .i_mul1_rd(mul1_rd),
        .i_mul2_valid(mul2_valid),
        .i_mul2_rd(mul2_rd),
        .i_mul3_valid(mul3_valid),
        .i_mul3_rd(mul3_rd),
        .i_branch_taken(ex_branch_taken),
        .i_id_instr_type(id_instr_type),
        .o_data_hazard(data_hazard),
        .o_flush(flush)
    );

    //& ===============
    //& GLOBAL DATA MEMORY CROSSBAR
    //& ===============

    wire [NUM_CORES*`DMEM_AW-1:0] flat_mem_addr;
    wire [NUM_CORES*32-1:0] flat_mem_wdata;
    wire [NUM_CORES*32-1:0] flat_mem_rdata;

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

    //& ===============
    //& STREAMING PROCESSOR CORES
    //& ===============
    wire [NUM_CORES-1:0] core_ex_branch_taken, core_complete;
    wire [$clog2(`IMEM_ENTRIES)-1:0] core_ex_beq_target_idx [0:NUM_CORES-1];
    wire [NUM_CORES-1:0] core_mul1_valid, core_mul2_valid, core_mul3_valid;
    wire [4:0] core_mul1_rd [0:NUM_CORES-1];
    wire [4:0] core_mul2_rd [0:NUM_CORES-1];
    wire [4:0] core_mul3_rd [0:NUM_CORES-1];

    // Since execution is lockstep, use Core 0 for shared hazard tracking
    assign ex_branch_taken = core_ex_branch_taken[0];
    assign ex_beq_target_idx = core_ex_beq_target_idx[0];
    assign mul1_valid = core_mul1_valid[0];
    assign mul1_rd = core_mul1_rd[0];
    assign mul2_valid = core_mul2_valid[0];
    assign mul2_rd = core_mul2_rd[0];
    assign mul3_valid = core_mul3_valid[0];
    assign mul3_rd = core_mul3_rd[0];
    assign o_kernel_complete = core_complete[0]; //! Assign first one since divergence isnt supported

    generate
        for (i = 0; i < NUM_CORES; i = i + 1) begin : cores

            StreamingProcessor #(.CORE_ID(i)) core (
                .clk(clk),
                .rst(rst),

                //! Regfile Muxes forward
                .i_id_mux_rs1(id_mux_rs1),
                .i_id_mux_rs2(id_mux_rs2),

                //! IDEX Pipeline
                .i_idex_rs1(idex_rs1),
                .i_idex_rs2(idex_rs2),
                .i_idex_rd(idex_rd),
                .i_idex_imm_31_12(idex_imm_31_12),
                .i_idex_imm_31_20(idex_imm_31_20),
                .i_idex_imm_31_25(idex_imm_31_25),
                .i_idex_funct3(idex_funct3),
                .i_idex_aluop(idex_aluop),
                .i_idex_instr_type(idex_instr_type),
                .i_idex_opcode(idex_opcode),
                .i_idex_program_counter(idex_program_counter),
                .i_idex_wen(idex_wen),

                //! Feedback wires Hazard & PC 
                .o_ex_branch_taken(core_ex_branch_taken[i]),
                .o_ex_beq_target_idx(core_ex_beq_target_idx[i]),
                .o_mul1_valid(core_mul1_valid[i]),
                .o_mul1_rd(core_mul1_rd[i]),
                .o_mul2_valid(core_mul2_valid[i]),
                .o_mul2_rd(core_mul2_rd[i]),
                .o_mul3_valid(core_mul3_valid[i]),
                .o_mul3_rd(core_mul3_rd[i]),

                //! Memory connections to Crossbar
                .o_mem_addr(sp_mem_addr[i]),
                .o_mem_wdata(sp_mem_wdata[i]),
                .o_mem_ren(sp_mem_ren[i]),
                .o_mem_wen(sp_mem_wen[i]),
                .i_mem_rdata(sp_mem_rdata[i]),
                
                //! New Crossbar Control Pins
                .i_mem_grant(sp_mem_grant[i]),
                .i_mem_rvalid(sp_mem_rvalid[i]),
                .i_global_stall(global_stall),
                .o_core_complete(core_complete[i])
            );
        end
    endgenerate

endmodule