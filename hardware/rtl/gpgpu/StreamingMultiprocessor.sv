`include "constants.svh"

module StreamingMultiprocessor #(
    parameter NUM_CORES = 32
) (
    input clk,
    input rst,
    input i_enable,

    input [31:0] i_ifid_instruction,
    output [`IMEM_AW-1:0] o_imem_addr,
    output o_imem_ren,

    MemoryInterface.master memory [NUM_CORES],
    input i_stall,

    output o_kernel_complete
);
    wire ex_branch_taken;
    wire [$clog2(`IMEM_ENTRIES)-1:0] ex_beq_target_idx;
    wire data_hazard, flush;
    reg [4:0] idex_rd;

    //! =========================================================================
    //! STAGE 1: INSTRUCTION FETCH
    //! =========================================================================
    (* dont_touch = `DEBUG *) wire [$clog2(`IMEM_ENTRIES)+1:0] program_counter;
    wire [$clog2(`IMEM_ENTRIES)-1:0] instr_idx;

    (* dont_touch = `DEBUG *)
    GUCounter #(.BITS($clog2(`IMEM_ENTRIES))) 
        programCounter (.clk(clk), .i_set_reset({rst, ex_branch_taken}), .i_count_enable(!data_hazard && !stall), .i_count_set(ex_beq_target_idx + 1'b1), .o_count_cur(instr_idx));

    assign program_counter = {instr_idx, 2'b00};
    assign o_imem_ren = (!data_hazard && !stall) | flush;
    assign o_imem_addr = flush ? ex_beq_target_idx : instr_idx;

    //* =========================================================================
    //* PIPELINE REGISTER 1: INSTRUCTION FETCH -> INSTRUCTION DECODE
    //* =========================================================================
    reg [$clog2(`IMEM_ENTRIES)+1:0] ifid_program_counter;
    always @(posedge clk) begin
        if (!rst) begin
            ifid_program_counter <= `INITIAL_PC;
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
        end else if (stall) begin
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

                //! Memory
                .memory(memory[i]),

                //! Control Pins
                .i_stall(stall),
                .o_core_complete(core_complete[i])
            );
        end
    endgenerate

endmodule