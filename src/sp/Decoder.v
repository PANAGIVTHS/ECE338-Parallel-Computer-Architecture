`include "constants.vh"

module Decoder (
    input [31:0] i_instr,
    output [4:0] o_rs1,
    output [4:0] o_rs2,
    output [4:0] o_rd,
    output [19:0] o_imm_31_12,
    output [6:0] o_imm_31_25,
    output [11:0] o_imm_31_20,
    output [2:0] o_funct3,
    output reg [3:0] o_aluop,
    output reg [1:0] o_instr_type,
    output [6:0] opcode
);
    wire [2:0] funct3;
    wire [6:0] funct7;

    //! Extract fields from instruction
    assign o_imm_31_25 = i_instr[31:25];
    assign o_imm_31_20 = i_instr[31:20];
    assign o_imm_31_12 = i_instr[31:12];
    assign o_rs2 = i_instr[24:20];
    assign o_rs1 = i_instr[19:15];
    assign o_rd = i_instr[11:7];
    assign funct7 = i_instr[31:25];
    assign funct3 = i_instr[14:12];
    assign o_funct3 = funct3;
    assign opcode = i_instr[6:0];

    //! Determine ALU operation based on opcode and funct fields
    always @* begin
        case (opcode)
            `OP_R_TYPE: begin
                case ({funct7, funct3}) 
                    {`FUNCT7_ADD, `FUNCT3_ADD_SUB_MUL}: o_aluop = `ALU_ADD;
                    {`FUNCT7_SUB, `FUNCT3_ADD_SUB_MUL}: o_aluop = `ALU_SUB;
                    {`FUNCT7_MULDIV, `FUNCT3_ADD_SUB_MUL}: o_aluop = `ALU_MUL;
                    {`FUNCT7_MULDIV, `FUNCT3_DIV}: o_aluop = `ALU_DIV;
                    {`FUNCT7_ADD, `FUNCT3_XOR}: o_aluop = `ALU_XOR;
                    {`FUNCT7_ADD, `FUNCT3_OR}:  o_aluop = `ALU_OR;
                    {`FUNCT7_ADD, `FUNCT3_SLL}: o_aluop = `ALU_SLL;
                    {`FUNCT7_SUB, `FUNCT3_SRA}: o_aluop = `ALU_SRA;
                    {`FUNCT7_ADD, `FUNCT3_AND}: o_aluop = `ALU_AND;
                    {`FUNCT7_ADD, `FUNCT3_SRL}:  o_aluop = `ALU_SRL;
                    {`FUNCT7_ADD, `FUNCT3_SLT}:  o_aluop = `ALU_SLT;
                    {`FUNCT7_ADD, `FUNCT3_SLTU}: o_aluop = `ALU_SLTU;
                    default:
                        o_aluop = `ALU_ADD;
                endcase
                o_instr_type = `INSTR_TYPE_R;
            end
            `OP_LW: begin 
                o_aluop = `ALU_ADD;
                o_instr_type = `INSTR_TYPE_I;
            end
            `OP_ADDI: begin
                o_instr_type = `INSTR_TYPE_I;
                case (funct3)
                    `FUNCT3_AND: o_aluop = `ALU_AND;
                    `FUNCT3_XOR: o_aluop = `ALU_XOR;
                    `FUNCT3_OR: o_aluop = `ALU_OR;
                    `FUNCT3_SLL: o_aluop = `ALU_SLL;
                    `FUNCT3_SLT: o_aluop = `ALU_SLT;
                    `FUNCT3_SLTU: o_aluop = `ALU_SLTU;                    
                    `FUNCT3_SRL: begin
                        if (funct7 == `FUNCT7_SUB)
                            o_aluop = `ALU_SRA;
                        else
                            o_aluop = `ALU_SRL;
                    end
                    default: o_aluop = `ALU_ADD;
                endcase
            end
            `OP_SW: begin 
                o_aluop = `ALU_ADD;
                o_instr_type = `INSTR_TYPE_S;
            end
            `OP_BEQ: begin 
                o_instr_type = `INSTR_TYPE_S;
                case (funct3)
                    `FUNCT3_BEQ: o_aluop = `ALU_SUB;
                    `FUNCT3_BNE: o_aluop = `ALU_SUB;
                    `FUNCT3_BLT: o_aluop = `ALU_SLT;
                    `FUNCT3_BGE: o_aluop = `ALU_SLT;
                    `FUNCT3_BLTU: o_aluop = `ALU_SLTU;
                    `FUNCT3_BGEU: o_aluop = `ALU_SLTU;
                    default: o_aluop = `ALU_SUB;
                endcase
            end
            `OP_JAL: begin
                o_aluop = `ALU_ADD;
                o_instr_type = `INSTR_TYPE_U;
            end
            `OP_JALR: begin
                o_aluop = `ALU_ADD;
                o_instr_type = `INSTR_TYPE_I;
            end
            `OP_LUI: begin
                o_aluop = `ALU_LUI;
                o_instr_type = `INSTR_TYPE_U;
            end
            default: begin
                o_aluop = `ALU_ADD; 
                o_instr_type = `INSTR_TYPE_R;
            end
        endcase
    end
endmodule
