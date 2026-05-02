`include "constants.vh"

module Decoder (
    input [31:0] i_instr,
    output [4:0] o_rs1,
    output [4:0] o_rs2,
    output [4:0] o_rd,
    output [6:0] o_imm_31_25,
    output [11:0] o_imm_31_20,
    output reg [1:0] o_aluop,
    output reg [1:0] o_instr_type,
    output [6:0] opcode
);
    wire [2:0] funct3;
    wire [6:0] funct7;

    //! Extract fields from instruction
    assign o_imm_31_25 = i_instr[31:25];
    assign o_imm_31_20 = i_instr[31:20];
    assign o_rs2 = i_instr[24:20];
    assign o_rs1 = i_instr[19:15];
    assign o_rd = i_instr[11:7];
    assign funct7 = i_instr[31:25];
    assign funct3 = i_instr[14:12];
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
                o_aluop = `ALU_ADD;
                o_instr_type = `INSTR_TYPE_I;
            end
            `OP_SW: begin 
                o_aluop = `ALU_ADD;
                o_instr_type = `INSTR_TYPE_S;
            end
            `OP_BEQ: begin 
                o_aluop = `ALU_ADD;
                o_instr_type = `INSTR_TYPE_S;
            end
            default: begin
                o_aluop = `ALU_ADD; 
                o_instr_type = `INSTR_TYPE_R;
            end
        endcase
    end
endmodule
