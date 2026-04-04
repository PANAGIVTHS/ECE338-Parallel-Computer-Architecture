module StreamingProcessor (
    input clk,
    input rst,
    output [7:0] o_leds,
    input i_dummy_wen
);

    (* dont_touch = "yes" *) wire [31:0] instruction, program_counter;
    wire [29:0] instr_idx;
    wire [31:0] alu_in_a, alu_in_b;
    wire [31:0] o_reg_a;
    wire [31:0] o_reg_b;
    wire [31:0] mem_out;
    (* dont_touch = "yes" *) wire [31:0] alu_out;
    wire [6:0] imm_31_25, opcode;
    wire [31:0] wb_wdata;
    wire [11:0] imm_31_20;
    wire [1:0] aluop, instr_type;
    wire [4:0] rs1, rs2, rd;
    wire zero, wen;
    wire is_load, is_store;

    wire [31:0] debug_signals = program_counter ^ alu_out ^ instruction;

    assign o_leds = debug_signals[31:24] ^ 
                    debug_signals[23:16] ^ 
                    debug_signals[15:8]  ^ 
                    debug_signals[7:0];

    assign wen = (instr_type == `INSTR_TYPE_R) || (instr_type == `INSTR_TYPE_I);

    // TODO: set values when we implement branching and jumping
    //! Counter returns instruction index not address!
    GUCounter #(.BITS(30)) 
        program_counter_inst (.clk(clk), .i_set_reset({rst, 1'b0}), .i_count_enable(1'b1), .i_count_set(30'b0), .o_count_cur(instr_idx));
    
    assign program_counter = {instr_idx, 2'b00};

    Memory instructionMemory (.clk(clk), .rst(rst), .i_read_addr(program_counter[11:2]), .i_read_enable(1'b1), .i_write_addr(program_counter[11:2]),
                              .i_write_enable(i_dummy_wen), .i_write_data(alu_out), .o_out(instruction));

    // TODO: add instruction fetch module to get instruction from memory 
    // InstrFetch instr_fetch_inst (.clk(clk), .rst(rst), .i_program_counter(program_counter), .o_fetched_instr(instruction));
    Decoder decoder_inst (.i_instr(instruction), .o_rs1(rs1), .o_rs2(rs2), .o_rd(rd), .o_imm_31_25(imm_31_25), .o_imm_31_20(imm_31_20), .o_aluop(aluop), .o_instr_type(instr_type), .opcode(opcode));
    Regfile regfile_inst (.clk(clk), .rst(rst), .i_wen(wen), .i_wdata(wb_wdata), .i_addr_a(rs1), .i_addr_b(rs2), .i_waddr(rd), .o_reg_a(o_reg_a), .o_reg_b(o_reg_b));
    assign alu_in_b = (instr_type == `INSTR_TYPE_I) ? {{20{imm_31_20[11]}}, imm_31_20} : o_reg_b;

    ALU alu_inst (.i_operand_a(o_reg_a), .i_operand_b(alu_in_b), .i_alu_op(aluop), .o_alu_out(alu_out), .o_alu_zero(zero));
    
    assign is_load = (opcode == `OP_LW);
    assign is_store = (opcode == `OP_SW);

    // LoadStoreUnit load_store_unit_inst (.clk(clk), .rst(rst), .i_write_enable(is_store), .i_read_enable(is_load), .i_addr(alu_out), .i_wdata(o_reg_b), .o_rdata(mem_out));

    // TODO: add logic to determine when to write back to regfile

    // TODO: and determine the data to write back Load vs ALU output
    //! wb_wdata is set 1 cycle after mem_out
    assign wb_wdata = is_load ? mem_out : alu_out;

    // TODO: add memory module
endmodule
