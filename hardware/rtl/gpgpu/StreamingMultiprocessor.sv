module StreamingMultiprocessor
    import gpu_pkg::*;
    import riscv_pkg::*;
    import alu_pkg::*;
    import pipeline_pkg::*;
#(
    parameter int unsigned NUM_CORES = 32
)(
    input logic clk,
    input logic rst_n,
    input logic i_enable,

    input word_t i_ifid_instruction,
    output imem_idx_t o_imem_addr,
    output logic o_imem_ren,

    MemorySubsystemInterface.requester memory_bus [NUM_CORES],
    
    output logic o_kernel_complete
);
    logic ex_branch_taken;
    imem_idx_t ex_beq_target_idx;
    logic data_hazard, flush;

    // Memory stall signal
    logic stall;

    //! =========================================================================
    //! STAGE 1: INSTRUCTION FETCH
    //! =========================================================================
    pc_t program_counter;
    imem_idx_t instr_idx;

    GUCounter #(.BITS(IMEM_AW)) 
        programCounter (.clk(clk), .i_set_reset({rst_n, ex_branch_taken}), .i_count_enable(!data_hazard && !stall), .i_count_set(ex_beq_target_idx + 1'b1), .o_count_cur(instr_idx));

    assign program_counter = {instr_idx, 2'b00};
    assign o_imem_ren = (!data_hazard && !stall) | flush;
    assign o_imem_addr = flush ? ex_beq_target_idx : instr_idx;

    //* =========================================================================
    //* PIPELINE REGISTER 1: INSTRUCTION FETCH -> INSTRUCTION DECODE
    //* =========================================================================
    pc_t ifid_program_counter;
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            ifid_program_counter <= INITIAL_PC;
        end else if (stall) begin
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
        if (!rst_n) begin
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
        if (!rst_n) begin
            idex <= '0;
            idex.program_counter <= INITIAL_PC;
        end else if (stall) begin
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
    //& STREAMING PROCESSOR CORES
    //& ===============

    // Since execution is lockstep, use Core 0 for shared hazard tracking
    assign ex_branch_taken = sp_feedback[0].branch_taken;
    assign ex_beq_target_idx = sp_feedback[0].branch_target_idx;
    assign o_kernel_complete = core_complete[0]; //! Assign first_n one since divergence isnt supported

    logic [NUM_CORES-1:0] mem_response_received;
    logic [NUM_CORES-1:0] mem_is_mem_vec;
    assign stall = !i_enable || (!(&mem_response_received) && mem_is_mem_vec[0]);

    generate
        for (genvar i = 0; i < NUM_CORES; i = i + 1) begin : cores

            StreamingProcessor #(.CORE_ID(i)) core (
                .clk(clk),
                .rst_n(rst_n),

                //! Regfile Muxes forward
                .i_id_mux_rs1(decoded.rs1),
                .i_id_mux_rs2(decoded.rs2),

                //! IDEX Pipeline
                .i_idex(idex),

                //! Feedback wires Hazard & PC
                .o_feedback(sp_feedback[i]),

                //! Memory
                .memory_if(memory_bus[i]),
                .mem_response_received(mem_response_received[i]),
                .mem_is_mem(mem_is_mem_vec[i]),

                //! Control Pins
                .i_stall(stall),
                .o_core_complete(core_complete[i])
            );
        end
    endgenerate

endmodule
