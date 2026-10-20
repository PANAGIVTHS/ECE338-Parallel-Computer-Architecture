module StreamingMultiprocessor
    import gpu_pkg::*;
    import riscv_pkg::*;
    import alu_pkg::*;
    import pipeline_pkg::*;
#(
    parameter int unsigned NUM_CORES = 32
)(
    input logic clk,
    input logic rst,
    input logic i_enable,

    input word_t i_ifid_instruction,
    output imem_idx_t o_imem_addr,
    output logic o_imem_ren,

    MemoryInterface.master dmem_a, dmem_b,
    
    output logic o_kernel_complete
);
    logic ex_branch_taken;
    imem_idx_t ex_beq_target_idx;
    logic data_hazard, flush;

    //& ===============
    //& CROSSBAR & STALL LOGIC
    //& ===============
    MemoryInterface #(.ADDR_WIDTH(DMEM_AW)) sp_mem [NUM_CORES] ();
    MemoryInterface #(.ADDR_WIDTH(DMEM_AW)) arb_mem [NUM_CORES] ();
    logic [NUM_CORES-1:0] sp_mem_ren, sp_mem_wen, sp_mem_grant;
    logic [NUM_CORES-1:0] mem_satisfied;

    //! Only request memory if the core hasn't already been served during this stall
    logic [NUM_CORES-1:0] active_mem_ren;
    assign active_mem_ren = sp_mem_ren & ~mem_satisfied;
    logic [NUM_CORES-1:0] active_mem_wen;
    assign active_mem_wen = sp_mem_wen & ~mem_satisfied;

    //! If even a single core asks for memory but is denied, stall (Handles Reads and Writes)
    logic global_stall;
    assign global_stall = (|(active_mem_ren & ~sp_mem_grant) | |(active_mem_wen & ~sp_mem_grant)) || !i_enable;
    
    always_ff @(posedge clk) begin
        if (!rst) begin
            mem_satisfied <= '0;
        end else if (!global_stall) begin
            //! Reset when pipeline moves
            mem_satisfied <= '0;
        end else begin
            //! Accumulate grants
            mem_satisfied <= mem_satisfied | sp_mem_grant;
        end
    end

    //& ===============
    //& READ DATA LATCHING
    //& ===============
    word_t latched_rdata [0:NUM_CORES-1];
    logic [NUM_CORES-1:0] mem_grant_delayed;
    word_t arb_rdata [0:NUM_CORES-1];

    //! BRAM data arrives exactly 1 cycle after a grant. We delay the grant signal
    //! to know exactly when to latch the valid data from the crossbar.
    always_ff @(posedge clk) begin
        if (!rst) mem_grant_delayed <= '0;
        //! Only delay the grant signal if it belongs to a valid READ request
        else mem_grant_delayed <= sp_mem_grant & (sp_mem_ren & ~sp_mem_wen);
    end

    always_ff @(posedge clk) begin
        if (!rst) begin
            for (int k = 0; k < NUM_CORES; k = k + 1) begin 
                latched_rdata[k] <= '0;
            end
        end else begin
            for (int k = 0; k < NUM_CORES; k = k + 1) begin
                if (mem_grant_delayed[k]) begin
                    latched_rdata[k] <= arb_rdata[k];
                end
            end
        end
    end

    //! =========================================================================
    //! STAGE 1: INSTRUCTION FETCH
    //! =========================================================================
    pc_t program_counter;
    imem_idx_t instr_idx;

    GUCounter #(.BITS(IMEM_AW)) 
        programCounter (.clk(clk), .i_set_reset({rst, ex_branch_taken}), .i_count_enable(!data_hazard && !global_stall), .i_count_set(ex_beq_target_idx + 1'b1), .o_count_cur(instr_idx));

    assign program_counter = {instr_idx, 2'b00};
    assign o_imem_ren = (!data_hazard && !global_stall) | flush;
    assign o_imem_addr = flush ? ex_beq_target_idx : instr_idx;

    //* =========================================================================
    //* PIPELINE REGISTER 1: INSTRUCTION FETCH -> INSTRUCTION DECODE
    //* =========================================================================
    pc_t ifid_program_counter;
    always_ff @(posedge clk) begin
        if (!rst) begin
            ifid_program_counter <= INITIAL_PC;
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
    id_ex_t decoded, idex;
    logic id_is_mul;
    logic decode_enabled;

    always_ff @(posedge clk) begin
        if (!rst) begin
            decode_enabled <= 1'b0;
        end else begin
            decode_enabled <= i_enable;
        end
    end

    Decoder decoder (
        .i_instr(i_ifid_instruction),
        .i_program_counter(ifid_program_counter),
        .o_decoded(decoded)
    );

    assign id_is_mul = (decoded.opcode == OP_R_TYPE) && (decoded.imm_31_25 == FUNCT7_MULDIV);

    //* =========================================================================
    //* PIPELINE REGISTER 2: INSTRUCTION DECODE -> EXECUTE (Feeds into SP)
    //* =========================================================================
    always_ff @(posedge clk) begin
        if (!rst) begin
            idex <= '0;
            idex.program_counter <= INITIAL_PC;
        end else if (global_stall) begin
            // Retain state during memory stall
        end else if (!decode_enabled || data_hazard) begin
            idex <= '0;
            idex.program_counter <= ifid_program_counter;
            idex.alu_op <= ALU_OP_INVALID;
        end else begin
            idex <= decoded;
        end
    end
    

    //& ===============
    //& HAZARD DETECTION
    //& ===============
    logic sm_ex_is_load;
    assign sm_ex_is_load = (idex.opcode == OP_LW && idex.instr_type == INSTR_TYPE_I);
    logic sm_ex_is_mul;
    assign sm_ex_is_mul = (idex.opcode == OP_R_TYPE) && (idex.imm_31_25 == FUNCT7_MULDIV);
    
    //! SP wires
    sp_feedback_t sp_feedback [0:NUM_CORES-1];
    logic [NUM_CORES-1:0] core_complete;

    HazardUnit hazardUnit (
        .i_id_rs1(decoded.rs1),
        .i_id_rs2(decoded.rs2),
        .i_idex_rd(idex.rd),
        .i_ex_is_load(sm_ex_is_load),
        .i_ex_is_mul(sm_ex_is_mul),
        .i_id_is_mul(id_is_mul),
        .i_mul1(sp_feedback[0].mul1),
        .i_mul2(sp_feedback[0].mul2),
        .i_mul3(sp_feedback[0].mul3),
        .i_branch_taken(ex_branch_taken),
        .i_id_instr_type(decoded.instr_type),
        .o_data_hazard(data_hazard),
        .o_flush(flush)
    );

    //& ===============
    //& GLOBAL DATA MEMORY CROSSBAR
    //& ===============

    genvar i;
    generate
        for (i = 0; i < NUM_CORES; i = i + 1) begin : gen_flat
            assign sp_mem_ren[i] = sp_mem[i].ren;
            assign sp_mem_wen[i] = sp_mem[i].wen;
            assign sp_mem_grant[i] = arb_mem[i].grant;

            assign arb_mem[i].addr = sp_mem[i].addr;
            assign arb_mem[i].wdata = sp_mem[i].wdata;
            assign arb_mem[i].ren = active_mem_ren[i];
            assign arb_mem[i].wen = active_mem_wen[i];
            assign arb_rdata[i] = arb_mem[i].rdata;

            assign sp_mem[i].grant = arb_mem[i].grant;
            assign sp_mem[i].rvalid = arb_mem[i].rvalid;
            //! If granted exactly 1 cycle ago, read live directly from crossbar
            //! Otherwise (stalled for >1 cycle), read from the safety latch.
            assign sp_mem[i].rdata = mem_grant_delayed[i] ? arb_rdata[i] : latched_rdata[i];
        end
    endgenerate

    MemoryCrossbarNx2 #(
        .N(NUM_CORES),
        .DEPTH(DMEM_ENTRIES),
        .ADDR_W(DMEM_AW)
    ) memCrossbar (
        .clk(clk),
        .rst(rst),

        //! Cores Interface
        .cores(arb_mem),
        
        //! Memory Ports
        .memory_a(dmem_a),
        .memory_b(dmem_b)
    );

    //& ===============
    //& STREAMING PROCESSOR CORES
    //& ===============

    // Since execution is lockstep, use Core 0 for shared hazard tracking
    assign ex_branch_taken = sp_feedback[0].branch_taken;
    assign ex_beq_target_idx = sp_feedback[0].branch_target_idx;
    assign o_kernel_complete = core_complete[0]; //! Assign first one since divergence isnt supported

    generate
        for (i = 0; i < NUM_CORES; i = i + 1) begin : cores

            StreamingProcessor #(.CORE_ID(i)) core (
                .clk(clk),
                .rst(rst),

                //! Regfile Muxes forward
                .i_id_mux_rs1(decoded.rs1),
                .i_id_mux_rs2(decoded.rs2),

                //! IDEX Pipeline
                .i_idex(idex),

                //! Feedback wires Hazard & PC
                .o_feedback(sp_feedback[i]),

                //! Memory connections to Crossbar
                .memory(sp_mem[i]),
                .i_global_stall(global_stall),
                .o_core_complete(core_complete[i])
            );
        end
    endgenerate

endmodule