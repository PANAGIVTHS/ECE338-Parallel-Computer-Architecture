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

    //! Pipeline Register: IDEX -> EX
    input id_ex_t i_idex,

    //! Hazard and Branch feedback
    output sp_feedback_t o_feedback,
    output mul_hazard_t o_mul_hazards [0:MUL_LATENCY-1],

    //! Memory
    MemorySubsystemInterface.requester memory_if,
    output logic mem_response_received,
    output logic mem_is_mem,

    //! Control
    input i_stall
);

    ex_mem_t exmem;
    mul_stage_t mul_in, mul_out;
    word_t mul_res;

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
    word_t forwarded_rs2;
    word_t ex_store_data;
    word_t ex_actual_alu_in_a;
    word_t ex_actual_alu_in_b;
    forward_sel_t forward_alu_a, forward_alu_b;
    logic ex_is_mul, mul_not_ready;
    mem_wb_t memwb;
    word_t wb_wdata;

    assign ex_is_mul = (i_idex.opcode == OP_R_TYPE) && (i_idex.imm_31_25 == FUNCT7_MULDIV); //! WARNING when adding DIV mul would be confused with div 
    assign ex_imm_i_type = {{20{i_idex.imm_31_20[11]}}, i_idex.imm_31_20};
    assign ex_imm_s_type = {{20{i_idex.imm_31_25[6]}}, i_idex.imm_31_25, i_idex.rd};
    assign ex_imm_u_type = {i_idex.imm_31_12, 12'b0};

    (* dont_touch = `DEBUG *)
    Regfile #(
        .CORE_ID(CORE_ID)
    ) regfile (
        .clk(clk), .rst_n(rst_n), .i_wen(memwb.wen), .i_wdata(wb_wdata), 
        .i_addr_a(i_id_mux_rs1), .i_addr_b(i_id_mux_rs2), .i_waddr(memwb.rd), 
        .o_reg_a(ex_reg_a), .o_reg_b(ex_reg_b), .i_stall(i_stall)
    );

    //? --- Forwarding Multiplexer B ---
    assign forwarded_rs2 = (forward_alu_b == EXALU_MEMALU_DEP) ? exmem.alu_out :
                           (forward_alu_b == MEMWB_EXALU_DEP)  ? wb_wdata : 
                            ex_reg_b;

    //? --- Store Data ---
    //! Repeat a byte or halfword across the word, so it is on the lanes that
    //! wstrb selects at any aligned address.
    always_comb begin
        case (i_idex.funct3)
            FUNCT3_SB: ex_store_data = {4{forwarded_rs2[7:0]}};
            FUNCT3_SH: ex_store_data = {2{forwarded_rs2[15:0]}};
            default:   ex_store_data = forwarded_rs2;
        endcase
    end

    //? --- Forwarding Multiplexer A ---
    //! U-type instructions have no rs1: JAL and AUIPC add to the PC, LUI ignores A.
    assign ex_actual_alu_in_a = (i_idex.instr_type == INSTR_TYPE_U) ? i_idex.program_counter :
                                (forward_alu_a == EXALU_MEMALU_DEP) ? exmem.alu_out :
                                (forward_alu_a == MEMWB_EXALU_DEP)  ? wb_wdata :
                                 ex_reg_a;

    //? --- Final ALU Input B ---
    always_comb begin
        if (i_idex.opcode == OP_JAL) begin
            ex_actual_alu_in_b = 32'd4;
        end else if (i_idex.opcode == OP_LW || i_idex.instr_type == INSTR_TYPE_I) begin
            ex_actual_alu_in_b = ex_imm_i_type;
        end else if (i_idex.opcode == OP_SW) begin
            ex_actual_alu_in_b = ex_imm_s_type;
        end else if (i_idex.instr_type == INSTR_TYPE_U) begin
            ex_actual_alu_in_b = ex_imm_u_type;
        end else begin
            ex_actual_alu_in_b = forwarded_rs2;
        end
    end
    
    (* dont_touch = `DEBUG *)
    ALU alu (
        .i_operand_a(ex_actual_alu_in_a), 
        .i_operand_b(ex_actual_alu_in_b),
        .i_alu_op(i_idex.alu_op), 
        .i_mul_valid(mul_out.hazard.valid),
        .i_mul_res(mul_res),
        .o_alu_out(ex_alu_out),
        .o_alu_zero(ex_zero)
    );

    assign mul_in = '{
        program_counter: i_idex.program_counter,
        hazard: '{
            valid: ex_is_mul && (i_idex.rd != '0),
            rd: ex_is_mul ? i_idex.rd : '0
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

    assign o_feedback.exit_in_ex = i_idex.is_ecall && (ex_actual_alu_in_a == '0);

    assign ex_is_branch = (i_idex.opcode == OP_BEQ);
    assign ex_is_jal = (i_idex.opcode == OP_JAL);
    assign ex_is_jalr = (i_idex.opcode == OP_JALR);
    assign ex_branch_condition_met =
        (i_idex.funct3 == FUNCT3_BEQ) ? (ex_zero) :
        (i_idex.funct3 == FUNCT3_BNE) ? (!ex_zero) :
        (i_idex.funct3 == FUNCT3_BLT) ? (ex_alu_out) :
        (i_idex.funct3 == FUNCT3_BGE) ? (!ex_alu_out) :
        (i_idex.funct3 == FUNCT3_BLTU) ? (ex_alu_out) :
        (i_idex.funct3 == FUNCT3_BGEU) ? (!ex_alu_out) :
        1'b0;
    assign o_feedback.branch_taken = (ex_is_branch && ex_branch_condition_met) || ex_is_jal || ex_is_jalr;

    assign ex_beq_offset = {{20{i_idex.imm_31_25[6]}}, i_idex.rd[0], i_idex.imm_31_25[5:0], i_idex.rd[4:1], 1'b0};
    assign ex_jal_offset = {{12{i_idex.imm_31_12[19]}}, i_idex.imm_31_12[7:0], i_idex.imm_31_12[8], i_idex.imm_31_12[18:9], 1'b0};
    assign ex_jalr_target_addr = ex_alu_out & 32'hFFFF_FFFE;

    assign ex_branch_operand_a = ex_is_jalr ? i_idex.program_counter : i_idex.program_counter[$clog2(IMEM_ENTRIES)+1:2];
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
                reg_b: ex_store_data,
                mul_valid: mul_out.hazard.valid,
                rd: mul_out.hazard.valid ? mul_out.hazard.rd : i_idex.rd,
                funct3: i_idex.funct3,
                opcode: mul_out.hazard.valid ? OP_R_TYPE : i_idex.opcode,
                wen: mul_out.hazard.valid ? (mul_out.hazard.rd != '0) : (i_idex.wen && i_idex.rd != '0),
                program_counter: mul_out.hazard.valid ? mul_out.program_counter : i_idex.program_counter,
                exit_requested: o_feedback.exit_in_ex
            };
        end
    end

    //! =========================================================================
    //! STAGE 4: MEMORY
    //! =========================================================================
    logic mem_is_load, mem_is_store;
    word_t temp_memory;
    logic [1:0] mem_offset;
    MemorySubsystemPkg::mem_size_t mem_size;
    strb_t mem_wstrb;
    assign mem_is_load = (exmem.opcode == OP_LW);
    assign mem_is_store = (exmem.opcode == OP_SW);
    assign mem_is_mem = mem_is_load | mem_is_store;
    assign mem_offset = exmem.alu_out[1:0];
    assign mem_size = MemorySubsystemPkg::mem_size_t'(exmem.funct3[1:0]);

    //! The bytes a store writes. A misaligned store faults before it writes,
    //! so a lane lost to the shift does not matter.
    always_comb begin
        case (mem_size)
            MemorySubsystemPkg::MEM_SIZE_BYTE: mem_wstrb = strb_t'(4'b0001 << mem_offset);
            MemorySubsystemPkg::MEM_SIZE_HALF: mem_wstrb = strb_t'(4'b0011 << mem_offset);
            default:                           mem_wstrb = '1;
        endcase
    end

    assign memory_if.req_valid = !mem_response_received && (mem_is_load | mem_is_store);
    assign memory_if.req.addr = exmem.alu_out;
    assign memory_if.req.size = mem_size;
    assign memory_if.req.write = mem_is_store;
    assign memory_if.req.wdata = exmem.reg_b;
    assign memory_if.req.wstrb = mem_wstrb;

    assign memory_if.rsp_ready = 'b1;


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

    //? --- Load Data ---
    //! Bring the addressed bytes down, then extend. A halfword is at offset 0
    //! or 2 and a word at offset 0: the rest faults before it gets here.
    logic [7:0] mem_load_byte0, mem_load_byte1;
    word_t mem_load_data;
    assign mem_load_byte0 = temp_memory[{mem_offset, 3'b000} +: 8];
    assign mem_load_byte1 = mem_offset[1] ? temp_memory[31:24] : temp_memory[15:8];

    always_comb begin
        case (exmem.funct3)
            FUNCT3_LB:  mem_load_data = {{24{mem_load_byte0[7]}}, mem_load_byte0};
            FUNCT3_LBU: mem_load_data = {24'b0, mem_load_byte0};
            FUNCT3_LH:  mem_load_data = {{16{mem_load_byte1[7]}}, mem_load_byte1, mem_load_byte0};
            FUNCT3_LHU: mem_load_data = {16'b0, mem_load_byte1, mem_load_byte0};
            default:    mem_load_data = temp_memory;
        endcase
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
                rdata: mem_load_data,
                exit_requested: exmem.exit_requested
            };
        end
    end

    //! =========================================================================
    //! STAGE 5: WRITE BACK
    //! =========================================================================

    assign wb_wdata = memwb.is_load ? memwb.rdata : memwb.alu_out;
    assign o_feedback.exit_requested = memwb.exit_requested;

    //& ===============
    //& FORWARDING
    //& ===============
    (* dont_touch = `DEBUG *)
    ForwardingUnit forwardingUnit (
        .i_idex_rs1(i_idex.rs1),
        .i_idex_rs2(i_idex.rs2),
        .i_exmem_rd(exmem.rd),
        .i_exmem_wen(exmem.wen),
        .i_idex_instr_type(i_idex.instr_type),
        .i_memwb_rd(memwb.rd),
        .i_memwb_wen(memwb.wen),
        .o_forward_alu_a(forward_alu_a),
        .o_forward_alu_b(forward_alu_b)
    );

endmodule
