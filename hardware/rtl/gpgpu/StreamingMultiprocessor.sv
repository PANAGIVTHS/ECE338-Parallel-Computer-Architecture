module StreamingMultiprocessor
    import gpu_pkg::*;
    import riscv_pkg::*;
    import alu_pkg::*;
    import pipeline_pkg::*;
    import MemorySubsystemPkg::*;
    import warp_pkg::*;
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
    
    output logic o_kernel_complete,

    // Fault capture: sticky until the SM reset at START
    output logic o_fault,
    output logic [NUM_CORES-1:0] o_fault_lanes,
    output mem_status_kinds_t o_fault_kinds,
    output pc_t o_fault_pc
);
    logic ex_branch_taken;
    imem_idx_t ex_beq_target_idx;
    logic data_hazard, flush;
    sp_feedback_t sp_feedback [0:NUM_CORES-1];

    // Memory stall signal
    logic stall;

    //! Halt: once the exit ECALL leaves EX nothing younger may issue, so the
    //! stages behind it fill with bubbles while the older ones retire.
    logic exit_now, exiting, issue_enabled;
    assign exit_now = sp_feedback[0].exit_in_ex && !stall;
    assign issue_enabled = !exiting && !exit_now;

    always_ff @(posedge clk) begin
        if (!rst_n) exiting <= 1'b0;
        else if (exit_now) exiting <= 1'b1;
    end

    //! =========================================================================
    //! STAGE 1: INSTRUCTION FETCH
    //! =========================================================================
    pc_t program_counter;
    imem_idx_t instr_idx;

    GUCounter #(.BITS(IMEM_AW)) 
        programCounter (.clk(clk), .i_set_reset({rst_n, ex_branch_taken}), .i_count_enable(issue_enabled && !data_hazard && !stall), .i_count_set(ex_beq_target_idx + 1'b1), .o_count_cur(instr_idx));

    assign program_counter = {instr_idx, 2'b00};
    assign o_imem_ren = issue_enabled && ((!data_hazard && !stall) | flush);
    assign o_imem_addr = flush ? ex_beq_target_idx : instr_idx; // TODO Change when flush happens for multiple reasons

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
        end else if (issue_enabled && !data_hazard) begin
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
        end else if (!issue_enabled || !decode_enabled || data_hazard) begin
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
    mul_hazard_t sp_mul_hazards [0:NUM_CORES-1][0:MUL_LATENCY-1];

    HazardUnit #(.MUL_LATENCY(MUL_LATENCY)) hazardUnit (
        .i_id_rs1(decoded.rs1),
        .i_id_rs2(decoded.rs2),
        .i_idex_rd(idex.rd),
        .i_ex_is_load(sm_ex_is_load),
        .i_ex_is_mul(sm_ex_is_mul),
        .i_id_is_mul(id_is_mul),
        .i_mul(sp_mul_hazards[0]),
        .i_branch_taken(ex_branch_taken),
        .i_id_instr_type(decoded.instr_type),
        .o_data_hazard(data_hazard),
        .o_flush(flush)
    );

    //& ===============
    //& STREAMING PROCESSOR CORES
    //& ===============

    // Since execution is lockstep, use Core 0 for shared hazard tracking
    assign ex_branch_taken = sp_feedback[0].branch_taken && !stall;
    assign ex_beq_target_idx = sp_feedback[0].branch_target_idx;
    assign o_kernel_complete = !stall && (sp_feedback[0].exit_requested);

    logic [NUM_CORES-1:0] mem_response_received;
    logic [NUM_CORES-1:0] mem_is_mem_vec;
    // A fault stalls in the cycle its response arrives, so the next
    // instruction never issues even when that response is the last one.
    assign stall = !i_enable || (!(&mem_response_received) && mem_is_mem_vec[0]) || o_fault;

    //& ===============
    //& FAULT CAPTURE
    //& ===============
    // A lane faults when its memory response carries a non-OK status. The
    // captures cover the faulting instruction: nothing issues after a fault,
    // but lanes already in flight still complete (and may add bits) while the
    // controller drains.
    logic [NUM_CORES-1:0] rsp_valid_vec;
    mem_status_t rsp_status_vec [NUM_CORES];
    for (genvar i = 0; i < NUM_CORES; i++) begin : g_lane_rsp
        assign rsp_valid_vec[i] = memory_bus[i].rsp_valid;
        assign rsp_status_vec[i] = memory_bus[i].rsp.status;
    end

    logic [NUM_CORES-1:0] lane_fault;
    mem_status_kinds_t lane_kinds;
    always_comb begin
        lane_kinds = '0;
        for (int unsigned i = 0; i < NUM_CORES; i++) begin
            lane_fault[i] = rsp_valid_vec[i] && (rsp_status_vec[i] != ST_OK);
            if (lane_fault[i]) begin
                lane_kinds[rsp_status_vec[i] - 1] = 1'b1;
            end
        end
    end

    logic fault_q;
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            fault_q <= 1'b0;
            o_fault_lanes <= '0;
            o_fault_kinds <= '0;
            o_fault_pc <= pc_t'(INITIAL_PC);
        end else begin
            o_fault_lanes <= o_fault_lanes | lane_fault;
            o_fault_kinds <= o_fault_kinds | lane_kinds;
            if ((|lane_fault) && !fault_q) begin
                fault_q <= 1'b1;
                // Lockstep: every lane is at the same instruction.
                o_fault_pc <= sp_feedback[0].mem_program_counter;
            end
        end
    end

    assign o_fault = fault_q || (|lane_fault);

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
                .o_mul_hazards(sp_mul_hazards[i]),

                //! Memory
                .memory_if(memory_bus[i]),
                .mem_response_received(mem_response_received[i]),
                .mem_is_mem(mem_is_mem_vec[i]),

                //! Control Pins
                .i_stall(stall)
            );
        end
    endgenerate

endmodule
