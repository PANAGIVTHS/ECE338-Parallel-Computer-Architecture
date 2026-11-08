`include "constants.svh"

module StreamingProcessor
    import gpu_pkg::*;
    import riscv_pkg::*;
    import pipeline_pkg::*;
    import alu_pkg::*;
#(
    parameter int unsigned CORE_ID = 0
)(
    input logic clk,
    input logic rst_n,

    //! Regfile Read Addresses
    input reg_addr_t i_id_mux_rs1,
    input reg_addr_t i_id_mux_rs2,

    //! The instruction in ID, decoded from this core's instruction-memory
    //! copy, and whether it enters EX (otherwise EX gets a bubble)
    input id_ex_t i_id_decoded,
    input logic i_id_issue,

    //! Forwarding for the instruction entering EX, from the SM's decode,
    //! and whether the registers it reads have been written since reset
    input forward_sel_t i_id_forward_a,
    input forward_sel_t i_id_forward_b,
    input logic i_id_written_a,
    input logic i_id_written_b,

    //! Hazard and Branch feedback
    output sp_feedback_t o_feedback,
    output mul_hazard_t o_mul_hazards [0:MUL_LATENCY-1],

    //! Memory
    MemorySubsystemInterface.requester memory_if,
    output logic mem_response_received,
    output logic mem_is_mem,

    //! Control
    input i_stall,
    output logic o_core_complete
);

    //! keep: the control fields are the same in every lockstep core, and a
    //! merged copy would drive all 32 cores' muxes and requests from afar
    (* keep = "true" *) ex_mem_t exmem;
    mul_stage_t mul_in, mul_out;
    word_t mul_res;

    //* =========================================================================
    //* PIPELINE REGISTER 2: INSTRUCTION DECODE -> EXECUTE (this core's copy)
    //* =========================================================================
    //! Every core keeps its own copy, so the opcode, immediates and selects of
    //! the instruction in EX stay local. A bubble keeps the instruction it
    //! replaces and clears idex_valid instead: the hazard logic drives one
    //! register per core, and every effect of the instruction checks it.
    (* keep = "true" *) id_ex_t idex;
    (* keep = "true" *) logic idex_valid;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            idex <= '0;
            idex.program_counter <= INITIAL_PC;
            idex_valid <= 1'b0;
        end else if (!i_stall) begin
            idex <= i_id_decoded;
            idex_valid <= i_id_issue;
        end
    end

    //! =========================================================================
    //! STAGE 3: EXECUTE
    //! =========================================================================
    word_t ex_alu_out;
    logic ex_zero, ex_is_branch, ex_is_jal, ex_is_jalr;
    logic ex_branch_condition_met;
    word_t ex_beq_offset, ex_jal_offset, ex_jalr_target_addr;
    word_t ex_branch_operand_a, ex_branch_operand_b, ex_branch_target_addr;
    word_t ex_imm_i_type, ex_imm_s_type, ex_imm_u_type;
    word_t ex_reg_a, ex_reg_b;
    word_t forwarded_rs1, forwarded_rs2;
    word_t ex_actual_alu_in_a;
    word_t ex_actual_alu_in_b;
    //! Registered with the instruction entering EX, like idex. Every core
    //! keeps its own copy: the selects drive this core's operand muxes only.
    (* keep = "true" *) forward_sel_t forward_alu_a;
    (* keep = "true" *) forward_sel_t forward_alu_b;
    logic ex_is_mul, mul_not_ready;
    (* keep = "true" *) mem_wb_t memwb;
    word_t wb_wdata;

    assign ex_is_mul = idex_valid && (idex.opcode == OP_R_TYPE) && (idex.imm_31_25 == FUNCT7_MULDIV); //! WARNING when adding DIV mul would be confused with div 
    assign ex_imm_i_type = {{20{idex.imm_31_20[11]}}, idex.imm_31_20};
    assign ex_imm_s_type = {{20{idex.imm_31_25[6]}}, idex.imm_31_25, idex.rd};
    assign ex_imm_u_type = {idex.imm_31_12, 12'b0};

    (* dont_touch = `DEBUG *)
    Regfile #(
        .CORE_ID(CORE_ID)
    ) regfile (
        .clk(clk), .rst_n(rst_n), .i_wen(memwb.wen), .i_wdata(wb_wdata), 
        .i_addr_a(i_id_mux_rs1), .i_addr_b(i_id_mux_rs2), .i_waddr(memwb.rd), 
        .i_written_a(i_id_written_a), .i_written_b(i_id_written_b),
        .o_reg_a(ex_reg_a), .o_reg_b(ex_reg_b), .i_stall(i_stall),
        .o_written_next(o_feedback.written_next)
    );

    //? --- Forwarding Multiplexer B ---
    assign forwarded_rs2 = (forward_alu_b == EXALU_MEMALU_DEP) ? exmem.alu_out :
                           (forward_alu_b == MEMWB_EXALU_DEP)  ? wb_wdata : 
                            ex_reg_b;

    //? --- Forwarding Multiplexer A ---
    assign forwarded_rs1 = (forward_alu_a == EXALU_MEMALU_DEP) ? exmem.alu_out :
                           (forward_alu_a == MEMWB_EXALU_DEP)  ? wb_wdata :
                            ex_reg_a;
    assign ex_actual_alu_in_a = (idex.opcode == OP_JAL) ? idex.program_counter : forwarded_rs1;

    //? --- Final ALU Input B ---
    always_comb begin
        if (idex.opcode == OP_JAL) begin
            ex_actual_alu_in_b = 32'd4;
        end else if (idex.opcode == OP_LW || idex.instr_type == INSTR_TYPE_I) begin
            ex_actual_alu_in_b = ex_imm_i_type;
        end else if (idex.opcode == OP_SW) begin
            ex_actual_alu_in_b = ex_imm_s_type;
        end else if (idex.instr_type == INSTR_TYPE_U) begin
            ex_actual_alu_in_b = ex_imm_u_type;
        end else begin
            ex_actual_alu_in_b = forwarded_rs2;
        end
    end
    
    (* dont_touch = `DEBUG *)
    ALU alu (
        .i_operand_a(ex_actual_alu_in_a), 
        .i_operand_b(ex_actual_alu_in_b),
        .i_alu_op(idex.alu_op), 
        .i_mul_valid(mul_out.hazard.valid),
        .i_mul_res(mul_res),
        .o_alu_out(ex_alu_out),
        .o_alu_zero(ex_zero)
    );

    assign mul_in = '{
        program_counter: idex.program_counter,
        hazard: '{
            valid: ex_is_mul && (idex.rd != '0),
            rd: ex_is_mul ? idex.rd : '0
        }
    };

    (* dont_touch = `DEBUG *)
    Multiplier #(.LATENCY(MUL_LATENCY)) multiplier (
        .clk(clk), .rst(rst_n),
        .i_operand_a(ex_actual_alu_in_a), .i_operand_b(ex_actual_alu_in_b),
        .i_global_stall(i_stall), .i_stage(mul_in),
        .o_result(mul_res), .o_stage(mul_out), .o_hazards(o_mul_hazards)
    );

    //! Output MUL for Hazard Unit
    always_comb begin
        mul_not_ready = ex_is_mul;
        for (int stage = 1; stage < MUL_LATENCY; stage++) begin
            mul_not_ready |= o_mul_hazards[stage-1].valid;
        end
        mul_not_ready &= !mul_out.hazard.valid;
    end

    assign ex_is_branch = idex_valid && (idex.opcode == OP_BEQ);
    assign ex_is_jal = idex_valid && (idex.opcode == OP_JAL);
    assign ex_is_jalr = idex_valid && (idex.opcode == OP_JALR);
    // Branch conditions and the JALR target come from their own comparator
    // and adder, not through the ALU's result mux: they steer the fetch.
    logic ex_rs_eq, ex_rs_lt, ex_rs_ltu;
    assign ex_rs_eq = forwarded_rs1 == forwarded_rs2;
    assign ex_rs_lt = $signed(forwarded_rs1) < $signed(forwarded_rs2);
    assign ex_rs_ltu = forwarded_rs1 < forwarded_rs2;
    assign ex_branch_condition_met =
        (idex.funct3 == FUNCT3_BEQ) ? ex_rs_eq :
        (idex.funct3 == FUNCT3_BNE) ? !ex_rs_eq :
        (idex.funct3 == FUNCT3_BLT) ? ex_rs_lt :
        (idex.funct3 == FUNCT3_BGE) ? !ex_rs_lt :
        (idex.funct3 == FUNCT3_BLTU) ? ex_rs_ltu :
        (idex.funct3 == FUNCT3_BGEU) ? !ex_rs_ltu :
        1'b0;
    assign o_feedback.branch_taken = (ex_is_branch && ex_branch_condition_met) || ex_is_jal || ex_is_jalr;

    assign ex_beq_offset = {{20{idex.imm_31_25[6]}}, idex.rd[0], idex.imm_31_25[5:0], idex.rd[4:1], 1'b0};
    assign ex_jal_offset = {{12{idex.imm_31_12[19]}}, idex.imm_31_12[7:0], idex.imm_31_12[8], idex.imm_31_12[18:9], 1'b0};
    assign ex_jalr_target_addr = (forwarded_rs1 + ex_imm_i_type) & 32'hFFFF_FFFE;

    assign ex_branch_operand_a = ex_is_jalr ? idex.program_counter : idex.program_counter[$clog2(IMEM_ENTRIES)+1:2];
    assign ex_branch_operand_b = ex_is_jalr ? 32'd4 : (ex_is_jal ? ex_jal_offset[31:2] : ex_beq_offset[31:2]);
    assign ex_branch_target_addr = ex_branch_operand_a + ex_branch_operand_b;
    assign o_feedback.branch_target_idx = ex_is_jalr
        ? ex_jalr_target_addr[$clog2(IMEM_ENTRIES)+1:2]
        : ex_branch_target_addr;
    assign o_feedback.mem_program_counter = exmem.program_counter;

    //* =========================================================================
    //* PIPELINE REGISTER 3: EXECUTE -> MEMORY
    //* =========================================================================
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            exmem <= pipeline_pkg::ex_mem_t'{
                program_counter: INITIAL_PC,
                opcode: OP_INVALID,
                default: '0
            };
        end else if (i_stall) begin
            // Retain state during memory stall
        end else if (mul_not_ready) begin
            exmem <= '{
                program_counter: INITIAL_PC,
                opcode: OP_INVALID,
                default: '0
            };
        end else begin
            exmem <= '{
                alu_out: (ex_is_jalr) ? ex_branch_target_addr : ex_alu_out,
                reg_b: forwarded_rs2,
                mul_valid: mul_out.hazard.valid,
                rd: mul_out.hazard.valid ? mul_out.hazard.rd : (idex_valid ? idex.rd : '0),
                opcode: mul_out.hazard.valid ? OP_R_TYPE : (idex_valid ? idex.opcode : OP_INVALID),
                wen: mul_out.hazard.valid ? (mul_out.hazard.rd != '0) : (idex_valid && idex.wen && idex.rd != '0),
                core_complete: ex_is_jalr &&
                               (idex.rd == '0) &&
                               (idex.rs1 == 5'd1) &&
                               (ex_imm_i_type == '0),
                program_counter: mul_out.hazard.valid ? mul_out.program_counter : idex.program_counter
            };
        end
    end

    //! =========================================================================
    //! STAGE 4: MEMORY
    //! =========================================================================
    logic mem_is_load, mem_is_store;
    word_t temp_memory;
    assign mem_is_load = (exmem.opcode == OP_LW);
    assign mem_is_store = (exmem.opcode == OP_SW);
    assign mem_is_mem = mem_is_load | mem_is_store;

    assign memory_if.req_valid = !mem_response_received && (mem_is_load | mem_is_store);
    assign memory_if.req.addr = exmem.alu_out;
    assign memory_if.req.write = mem_is_store;
    assign memory_if.req.wdata = exmem.reg_b;
    assign memory_if.req.wstrb = '1; // Full word write currently

    assign memory_if.rsp_ready = 'b1;

    assign o_core_complete = exmem.core_complete;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            temp_memory <= 'b0;
            mem_response_received <= 'b0;
        end else if (memory_if.rsp_ready && memory_if.rsp_valid) begin
            temp_memory <= memory_if.rsp.rdata;
            mem_response_received <= 'b1;
        end else if (!i_stall) begin
            mem_response_received <= 'b0;
        end
    end

    //! =========================================================================
    //! PIPELINE REGISTER 4: MEMORY -> WRITE BACK
    //! =========================================================================
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            memwb <= '{
                program_counter: INITIAL_PC,
                default: '0
            };
        end else if (i_stall) begin
            // Retain state during memory stall
        end else begin
            memwb <= '{
                rd: exmem.rd,
                is_mul: exmem.mul_valid,
                is_load: mem_is_load,
                alu_out: exmem.alu_out,
                wen: exmem.wen,
                program_counter: exmem.program_counter,
                rdata: temp_memory
            };
        end
    end

    //! =========================================================================
    //! STAGE 5: WRITE BACK
    //! =========================================================================

    assign wb_wdata = memwb.is_load ? memwb.rdata : memwb.alu_out;

    //& ===============
    //& FORWARDING
    //& ===============
    // The SM compares the instruction in ID with the writers it will meet in
    // EX: the one entering MEM now (exmem's next value) and the one in MEM
    // now (memwb's next value).
    writer_t ex_next_writer;
    always_comb begin
        if (mul_out.hazard.valid) begin
            ex_next_writer = '{rd: mul_out.hazard.rd, wen: mul_out.hazard.rd != '0};
        end else if (mul_not_ready) begin
            ex_next_writer = '{rd: '0, wen: 1'b0};
        end else begin
            ex_next_writer = '{rd: idex.rd, wen: idex_valid && idex.wen && (idex.rd != '0)};
        end
    end
    assign o_feedback.next_mem = ex_next_writer;
    assign o_feedback.next_wb = '{rd: exmem.rd, wen: exmem.wen};

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            forward_alu_a <= NO_DEP;
            forward_alu_b <= NO_DEP;
        end else if (!i_stall) begin
            forward_alu_a <= i_id_forward_a;
            forward_alu_b <= i_id_forward_b;
        end
    end

endmodule
