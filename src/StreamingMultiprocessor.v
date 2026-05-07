`include "constants.vh"

module StreamingMultiprocessor (
    input i_clk,
    input rst,
    input i_dummy_wen,
    output [2:0] o_leds
);

    wire clk;
    clk_wiz_0 clockDivider (
        .clk_in1(i_clk),
        .clk_out1(clk)
    );

    wire ex_branch_taken;
    wire [$clog2(`IMEM_ENTRIES)-1:0] ex_beq_target_idx;
    wire data_hazard, flush;
    reg [4:0] idex_rd;

    //& ===============
    //& CROSSBAR & STALL LOGIC
    //& ===============
    // New wires to connect the cores to the Crossbar
    wire [9:0] c0_mem_addr, c1_mem_addr;
    wire [31:0] c0_mem_wdata, c1_mem_wdata;
    wire c0_mem_ren, c1_mem_ren;
    wire c0_mem_wen, c1_mem_wen;
    wire [31:0] c0_mem_rdata, c1_mem_rdata;
    wire c0_mem_grant, c0_mem_rvalid;
    wire c1_mem_grant, c1_mem_rvalid;

    // If a core requests memory (ren) but doesn't get a grant, stall the whole pipeline
    wire global_stall = (c0_mem_ren & ~c0_mem_grant) | (c1_mem_ren & ~c1_mem_grant);

    //! =========================================================================
    //! STAGE 1: INSTRUCTION FETCH
    //! =========================================================================
    (* dont_touch = "true" *) wire [$clog2(`IMEM_ENTRIES)+1:0] program_counter;
    wire [31:0] ifid_instruction;
    wire [$clog2(`IMEM_ENTRIES)-1:0] instr_idx, instr_mem_addr;

    (* dont_touch = "true" *)
    GUCounter #(.BITS($clog2(`IMEM_ENTRIES))) 
        programCounter (.clk(clk), .i_set_reset({rst, ex_branch_taken}), .i_count_enable(!data_hazard && !global_stall), .i_count_set(ex_beq_target_idx), .o_count_cur(instr_idx));

    assign program_counter = {instr_idx, 2'b00};
    assign instr_mem_addr = flush ? `INITIAL_PC : instr_idx;

    (* dont_touch = "true" *)
    MemorySinglePort #(
        .DEPTH(`IMEM_ENTRIES),
        .INIT_FILE("program.mem")
    ) instructionMemory (
        .clk(clk),
        .i_addr_a(instr_mem_addr),
        .i_ren_a(!data_hazard | flush),
        .i_wen_a(1'b0),
        .i_data_a(32'b0),
        .o_out_a(ifid_instruction)
    );

    //* =========================================================================
    //* PIPELINE REGISTER 1: INSTRUCTION FETCH -> INSTRUCTION DECODE
    //* =========================================================================
    reg [$clog2(`IMEM_ENTRIES)+1:0] ifid_program_counter;
    always @(posedge clk) begin
        if (!rst) begin
            ifid_program_counter <= `INITIAL_PC;
        end else if (global_stall) begin
            // Retain state during memory stall
        end else if (!data_hazard) begin
            ifid_program_counter <= program_counter;
        end
    end

    //! =========================================================================
    //! STAGE 2: INSTRUCTION DECODE
    //! =========================================================================
    wire [6:0] id_imm_31_25, id_opcode;
    wire [11:0] id_imm_31_20;
    wire [1:0] id_aluop, id_instr_type;
    wire [4:0] id_rs1, id_rs2, id_rd;
    wire [4:0] id_mux_rs1, id_mux_rs2;
    wire id_is_mul, id_wen;

    (* dont_touch = "true" *)
    Decoder decoder (
        .i_instr(ifid_instruction),
        .o_rs1(id_rs1), 
        .o_rs2(id_rs2),
        .o_rd(id_rd),
        .o_imm_31_25(id_imm_31_25),
        .o_imm_31_20(id_imm_31_20),
        .o_aluop(id_aluop),
        .o_instr_type(id_instr_type),
        .opcode(id_opcode)
    );

    assign id_wen = !({`INSTR_TYPE_S == id_instr_type && `OP_SW == id_opcode} || {`INSTR_TYPE_S == id_instr_type && `OP_BEQ == id_opcode} || (id_rd == 5'b0));
    assign id_is_mul = (id_opcode == `OP_R_TYPE) && (id_imm_31_25 == `FUNCT7_MULDIV);
    
    assign id_mux_rs1 = data_hazard ? 5'b0 : id_rs1;
    assign id_mux_rs2 = data_hazard ? 5'b0 : id_rs2;

    //* =========================================================================
    //* PIPELINE REGISTER 2: INSTRUCTION DECODE -> EXECUTE (Feeds into SP)
    //* =========================================================================
    reg [4:0] idex_rs1, idex_rs2;
    reg [11:0] idex_imm_31_20;
    reg [1:0] idex_aluop, idex_instr_type;
    reg [6:0] idex_opcode, idex_imm_31_25;
    reg [$clog2(`IMEM_ENTRIES)+1:0] idex_program_counter;
    reg idex_wen;

    always @(posedge clk) begin
        if (!rst) begin
            idex_rs1 <= 5'b0;
            idex_rs2 <= 5'b0;
            idex_rd <= 5'b0;
            idex_imm_31_20 <= 12'b0;
            idex_aluop <= 2'b0;
            idex_instr_type <= 2'b0;
            idex_opcode <= 7'b0;
            idex_imm_31_25 <= 7'b0;
            idex_program_counter <= `INITIAL_PC;
            idex_wen <= 1'b0;
        end else if (global_stall) begin
            // Retain state during memory stall
        end else if (data_hazard) begin
            idex_rs1 <= 5'b0;
            idex_rs2 <= 5'b0;
            idex_rd <= 5'b0;
            idex_imm_31_20 <= 12'b0;
            idex_aluop <= `ALU_ADD;
            idex_instr_type <= `INSTR_TYPE_R;
            idex_opcode <= 7'b0;
            idex_imm_31_25 <= 7'b0;
            idex_program_counter <= ifid_program_counter;
            idex_wen <= 1'b0;
        end else begin
            idex_rs1 <= id_rs1;
            idex_rs2 <= id_rs2;
            idex_rd <= id_rd;
            idex_imm_31_20 <= id_imm_31_20;
            idex_imm_31_25 <= id_imm_31_25;
            idex_aluop <= id_aluop;
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

    (* dont_touch = "true" *)
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
    wire [9:0] sp0_mem_addr, sp1_mem_addr;
    wire [31:0] sp0_mem_wdata, sp1_mem_wdata;
    wire sp0_mem_ren, sp1_mem_ren;
    wire sp0_mem_wen, sp1_mem_wen;
    wire [31:0] sp0_mem_rdata, sp1_mem_rdata;

    MemoryCrossbarNx2 #(
        .N(2),
        .DEPTH(1024)
    ) memCrossbar (
        .clk(clk),
        .rst(rst),
        // Cores Interface
        .i_req   ( {c1_mem_ren, c0_mem_ren} ),     // Core ren acts as the global request
        .i_wen   ( {c1_mem_wen, c0_mem_wen} ),
        .i_addr  ( {c1_mem_addr, c0_mem_addr} ),
        .i_wdata ( {c1_mem_wdata, c0_mem_wdata} ),
        .o_grant ( {c1_mem_grant, c0_mem_grant} ),
        .o_rvalid( {c1_mem_rvalid, c0_mem_rvalid} ),
        .o_rdata ( {c1_mem_rdata, c0_mem_rdata} ),
        
        // Memory Port A Interface
        .o_addr_a(sp0_mem_addr),
        .o_ren_a(sp0_mem_ren),
        .o_wen_a(sp0_mem_wen),
        .o_data_a(sp0_mem_wdata),
        .i_out_a(sp0_mem_rdata),
        
        // Memory Port B Interface
        .o_addr_b(sp1_mem_addr),
        .o_ren_b(sp1_mem_ren),
        .o_wen_b(sp1_mem_wen),
        .o_data_b(sp1_mem_wdata),
        .i_out_b(sp1_mem_rdata)
    );

    //& ===============
    //& GLOBAL DATA MEMORY
    //& ===============
    (* dont_touch = "true" *)
    MemoryDualPort #(
        .DEPTH(1024),
        .INIT_FILE("")
    ) dataMemory (
        .clk(clk),
        .i_addr_a(sp0_mem_addr),
        .i_ren_a(sp0_mem_ren),
        .i_wen_a(sp0_mem_wen),
        .i_data_a(sp0_mem_wdata),
        .o_out_a(sp0_mem_rdata),
        .i_addr_b(sp1_mem_addr),
        .i_ren_b(sp1_mem_ren),
        .i_wen_b(sp1_mem_wen),
        .i_data_b(sp1_mem_wdata),
        .o_out_b(sp1_mem_rdata)
    );

    //& ===============
    //& STREAMING PROCESSOR CORES
    //& ===============
    StreamingProcessor #(.CORE_ID(0)) core_0 (
        .i_clk(clk),
        .rst(rst),
        .i_dummy_wen(i_dummy_wen),
        .o_leds(o_leds),

        //! Regfile Muxes forward
        .i_id_mux_rs1(id_mux_rs1),
        .i_id_mux_rs2(id_mux_rs2),

        //! IDEX Pipeline
        .i_idex_rs1(idex_rs1),
        .i_idex_rs2(idex_rs2),
        .i_idex_rd(idex_rd),
        .i_idex_imm_31_20(idex_imm_31_20),
        .i_idex_imm_31_25(idex_imm_31_25),
        .i_idex_aluop(idex_aluop),
        .i_idex_instr_type(idex_instr_type),
        .i_idex_opcode(idex_opcode),
        .i_idex_program_counter(idex_program_counter),
        .i_idex_wen(idex_wen),

        //! Feedback wires Hazard & PC 
        .o_ex_branch_taken(ex_branch_taken),
        .o_ex_beq_target_idx(ex_beq_target_idx),
        .o_mul1_valid(mul1_valid),
        .o_mul1_rd(mul1_rd),
        .o_mul2_valid(mul2_valid),
        .o_mul2_rd(mul2_rd),
        .o_mul3_valid(mul3_valid),
        .o_mul3_rd(mul3_rd),

        //! Memory connections to Crossbar
        .o_mem_addr(c0_mem_addr),
        .o_mem_wdata(c0_mem_wdata),
        .o_mem_ren(c0_mem_ren),
        .o_mem_wen(c0_mem_wen),
        .i_mem_rdata(c0_mem_rdata),
        
        //! New Crossbar Control Pins
        .i_mem_grant(c0_mem_grant),
        .i_mem_rvalid(c0_mem_rvalid),
        .i_global_stall(global_stall)
    );

    // Dummy wires to catch core_1's redundant lockstep feedback
    wire c1_ex_branch_taken;
    wire [$clog2(`IMEM_ENTRIES)-1:0] c1_ex_beq_target_idx;
    wire c1_mul1_valid, c1_mul2_valid, c1_mul3_valid;
    wire [4:0] c1_mul1_rd, c1_mul2_rd, c1_mul3_rd;
    wire [2:0] c1_leds;

    StreamingProcessor #(.CORE_ID(1)) core_1 (
        .i_clk(clk),
        .rst(rst),
        .i_dummy_wen(i_dummy_wen),
        .o_leds(c1_leds),

        //! Regfile Muxes forward
        .i_id_mux_rs1(id_mux_rs1),
        .i_id_mux_rs2(id_mux_rs2),

        //! IDEX Pipeline
        .i_idex_rs1(idex_rs1),
        .i_idex_rs2(idex_rs2),
        .i_idex_rd(idex_rd),
        .i_idex_imm_31_20(idex_imm_31_20),
        .i_idex_imm_31_25(idex_imm_31_25),
        .i_idex_aluop(idex_aluop),
        .i_idex_instr_type(idex_instr_type),
        .i_idex_opcode(idex_opcode),
        .i_idex_program_counter(idex_program_counter),
        .i_idex_wen(idex_wen),

        //! Feedback wires Hazard & PC (ignored for SM logic)
        .o_ex_branch_taken(c1_ex_branch_taken),
        .o_ex_beq_target_idx(c1_ex_beq_target_idx),
        .o_mul1_valid(c1_mul1_valid),
        .o_mul1_rd(c1_mul1_rd),
        .o_mul2_valid(c1_mul2_valid),
        .o_mul2_rd(c1_mul2_rd),
        .o_mul3_valid(c1_mul3_valid),
        .o_mul3_rd(c1_mul3_rd),

        //! Memory connections to Crossbar
        .o_mem_addr(c1_mem_addr),
        .o_mem_wdata(c1_mem_wdata),
        .o_mem_ren(c1_mem_ren),
        .o_mem_wen(c1_mem_wen),
        .i_mem_rdata(c1_mem_rdata),

        //! New Crossbar Control Pins
        .i_mem_grant(c1_mem_grant),
        .i_mem_rvalid(c1_mem_rvalid),
        .i_global_stall(global_stall)
    );

endmodule