
module Decoder
    import gpu_pkg::*;
    import riscv_pkg::*;
    import alu_pkg::*;
    import pipeline_pkg::*;
(
    input word_t i_instr,
    input pc_t i_program_counter,
    output id_ex_t o_decoded
);
    wire [2:0] funct3 = i_instr[14:12];
    wire [6:0] funct7 = i_instr[31:25];

    //! Extract fields from instruction
    opcode_t opcode;
    assign opcode = opcode_t'(i_instr[6:0]);

    //! Determine ALU operation based on opcode and funct fields
    always_comb begin

        o_decoded = '0;
        o_decoded.program_counter = i_program_counter;
        o_decoded.opcode = opcode;
        o_decoded.rs1 = i_instr[19:15];
        o_decoded.rs2 = i_instr[24:20];
        o_decoded.rd = i_instr[11:7];
        o_decoded.imm_31_12 = i_instr[31:12];
        o_decoded.imm_31_25 = i_instr[31:25];
        o_decoded.imm_31_20 = i_instr[31:20];
        o_decoded.funct3 = funct3;
        o_decoded.wen = (i_instr[11:7] != 5'b0) && (opcode != OP_SW) && (opcode != OP_BEQ);

        case (opcode)
            OP_R_TYPE: begin
                case ({funct7, funct3}) 
                    {FUNCT7_ADD, FUNCT3_ADD_SUB_MUL}: o_decoded.alu_op = ALU_OP_ADD;
                    {FUNCT7_SUB, FUNCT3_ADD_SUB_MUL}: o_decoded.alu_op = ALU_OP_SUB;
                    {FUNCT7_MULDIV, FUNCT3_ADD_SUB_MUL}: o_decoded.alu_op = ALU_OP_MUL;
                    {FUNCT7_MULDIV, FUNCT3_DIV}: o_decoded.alu_op = ALU_OP_DIV;
                    {FUNCT7_ADD, FUNCT3_XOR}: o_decoded.alu_op = ALU_OP_XOR;
                    {FUNCT7_ADD, FUNCT3_OR}:  o_decoded.alu_op = ALU_OP_OR;
                    {FUNCT7_ADD, FUNCT3_SLL}: o_decoded.alu_op = ALU_OP_SLL;
                    {FUNCT7_SUB, FUNCT3_SRA}: o_decoded.alu_op = ALU_OP_SRA;
                    {FUNCT7_ADD, FUNCT3_AND}: o_decoded.alu_op = ALU_OP_AND;
                    {FUNCT7_ADD, FUNCT3_SRL}:  o_decoded.alu_op = ALU_OP_SRL;
                    {FUNCT7_ADD, FUNCT3_SLT}:  o_decoded.alu_op = ALU_OP_SLT;
                    {FUNCT7_ADD, FUNCT3_SLTU}: o_decoded.alu_op = ALU_OP_SLTU;
                    default:
                        o_decoded.alu_op = ALU_OP_ADD;
                endcase
                o_decoded.instr_type = INSTR_TYPE_R;
            end
            OP_LW: begin 
                o_decoded.alu_op = ALU_OP_ADD;
                o_decoded.instr_type = INSTR_TYPE_I;
            end
            OP_ADDI: begin
                o_decoded.instr_type = INSTR_TYPE_I;
                case (funct3)
                    FUNCT3_AND: o_decoded.alu_op = ALU_OP_AND;
                    FUNCT3_XOR: o_decoded.alu_op = ALU_OP_XOR;
                    FUNCT3_OR: o_decoded.alu_op = ALU_OP_OR;
                    FUNCT3_SLL: o_decoded.alu_op = ALU_OP_SLL;
                    FUNCT3_SLT: o_decoded.alu_op = ALU_OP_SLT;
                    FUNCT3_SLTU: o_decoded.alu_op = ALU_OP_SLTU;                    
                    FUNCT3_SRL: begin
                        if (funct7 == FUNCT7_SUB)
                            o_decoded.alu_op = ALU_OP_SRA;
                        else
                            o_decoded.alu_op = ALU_OP_SRL;
                    end
                    default: o_decoded.alu_op = ALU_OP_ADD;
                endcase
            end
            OP_SW: begin 
                o_decoded.alu_op = ALU_OP_ADD;
                o_decoded.instr_type = INSTR_TYPE_S;
            end
            OP_BEQ: begin 
                o_decoded.instr_type = INSTR_TYPE_S;
                case (funct3)
                    FUNCT3_BEQ: o_decoded.alu_op = ALU_OP_SUB;
                    FUNCT3_BNE: o_decoded.alu_op = ALU_OP_SUB;
                    FUNCT3_BLT: o_decoded.alu_op = ALU_OP_SLT;
                    FUNCT3_BGE: o_decoded.alu_op = ALU_OP_SLT;
                    FUNCT3_BLTU: o_decoded.alu_op = ALU_OP_SLTU;
                    FUNCT3_BGEU: o_decoded.alu_op = ALU_OP_SLTU;
                    default: o_decoded.alu_op = ALU_OP_SUB;
                endcase
            end
            OP_JAL: begin
                o_decoded.alu_op = ALU_OP_ADD;
                o_decoded.instr_type = INSTR_TYPE_U;
            end
            OP_JALR: begin
                o_decoded.alu_op = ALU_OP_ADD;
                o_decoded.instr_type = INSTR_TYPE_I;
            end
            OP_LUI: begin
                o_decoded.alu_op = ALU_OP_LUI;
                o_decoded.instr_type = INSTR_TYPE_U;
            end
            OP_INVALID: begin
                o_decoded.alu_op = ALU_OP_INVALID;
                o_decoded.instr_type = INSTR_TYPE_R;
            end
            default: begin
                o_decoded.alu_op = ALU_OP_ADD; 
                o_decoded.instr_type = INSTR_TYPE_R;
            end
        endcase
    end
endmodule