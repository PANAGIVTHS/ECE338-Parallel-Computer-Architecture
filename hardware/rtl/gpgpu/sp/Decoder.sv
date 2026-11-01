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
    instruction_t instruction;
    assign instruction.bits = i_instr;

    always_comb begin
        o_decoded = '0;
        o_decoded.program_counter = i_program_counter;
        o_decoded.opcode = instruction.r.opcode;
        o_decoded.rs1 = instruction.r.rs1;
        o_decoded.rs2 = instruction.r.rs2;
        o_decoded.rd = instruction.r.rd;
        o_decoded.imm_31_12 = instruction.u.imm;
        o_decoded.imm_31_20 = instruction.i.imm;
        o_decoded.imm_31_25 = instruction.r.funct7;
        o_decoded.funct3 = instruction.r.funct3;
        o_decoded.wen = (instruction.r.rd != '0);

        case (instruction.r.opcode)
            OP_R_TYPE: begin
                case ({instruction.r.funct7, instruction.r.funct3})
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
            OP_LW, OP_JALR: begin 
                o_decoded.alu_op = ALU_OP_ADD;
                o_decoded.instr_type = INSTR_TYPE_I;
            end
            OP_ADDI: begin
                o_decoded.instr_type = INSTR_TYPE_I;
                case (instruction.r.funct3)
                    FUNCT3_AND: o_decoded.alu_op = ALU_OP_AND;
                    FUNCT3_XOR: o_decoded.alu_op = ALU_OP_XOR;
                    FUNCT3_OR: o_decoded.alu_op = ALU_OP_OR;
                    FUNCT3_SLL: o_decoded.alu_op = ALU_OP_SLL;
                    FUNCT3_SLT: o_decoded.alu_op = ALU_OP_SLT;
                    FUNCT3_SLTU: o_decoded.alu_op = ALU_OP_SLTU;                    
                    FUNCT3_SRL: begin
                        if (instruction.r.funct7 == FUNCT7_SUB)
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
                o_decoded.wen = 0;
            end
            OP_BEQ: begin 
                o_decoded.instr_type = INSTR_TYPE_S;
                case (instruction.r.funct3)
                    FUNCT3_BEQ, FUNCT3_BNE: o_decoded.alu_op = ALU_OP_SUB;
                    FUNCT3_BLT, FUNCT3_BGE: o_decoded.alu_op = ALU_OP_SLT;
                    FUNCT3_BLTU, FUNCT3_BGEU: o_decoded.alu_op = ALU_OP_SLTU;
                    default: o_decoded.alu_op = ALU_OP_SUB;
                endcase
                o_decoded.wen = 0;
            end
            OP_JAL: begin
                o_decoded.alu_op = ALU_OP_ADD;
                o_decoded.instr_type = INSTR_TYPE_U;
            end
            OP_LUI: begin
                o_decoded.alu_op = ALU_OP_LUI;
                o_decoded.instr_type = INSTR_TYPE_U;
            end
            OP_SYSTEM: begin
                o_decoded.is_ecall = (instruction.bits == ECALL_INSTR);

                //! Set ecall service register as it is not encoded by ECALL itself
                o_decoded.rs1 = o_decoded.is_ecall ? ECALL_SERVICE_REGISTER : '0; 
                o_decoded.rs2 = '0;
                o_decoded.rd = '0;
                o_decoded.wen = 1'b0;
                o_decoded.alu_op = ALU_OP_ADD;
                o_decoded.instr_type = INSTR_TYPE_I;
            end
            default: begin
                o_decoded.alu_op = ALU_OP_ADD; 
                o_decoded.instr_type = INSTR_TYPE_R;
            end
        endcase
    end
endmodule