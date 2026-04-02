`include "contanst.vh"

module Decoder (instruction, rs2, rs1, rd, imm_31_25, aluop);
    input [31:0] instruction;
    output [4:0] rs1, rs2, rd;
    output imm_31_25;
    output aluop;

    wire rs1, rs2, rd;
    wire [6:0] opcode;
    wire [2:0] funct3;
    wire [6:0] funct7;

    assign rs1 = instruction[19:15];
    assign rs2 = instruction[24:20];
    assign rd = instruction[11:7];
    assign imm_31_25 = instruction[31:25];
    assign funct3 = instruction[14:12];
    assign funct7 = instruction[31:25];

    always @* begin
        case (opcode) begin
            `OP_R_TYPE:
                case ({funct7, funct3}) begin
                    {`FUNCT7_ADD, `FUNCT3_ADD_SUB_MUL}: aluop = `ALU_ADD;
                    {`FUNCT7_SUB, `FUNCT3_ADD_SUB_MUL}: aluop = `ALU_SUB;
                    {`FUNCT7_MULDIV, `FUNCT3_ADD_SUB_MUL}: aluop = `ALU_MUL;
                    {`FUNCT7_MULDIV, `FUNCT3_DIV}: aluop = `ALU_DIV;
                    default:
                        aluop = `ALU_ADD;
                end
            `OP_LW:
                aluop = `ALU_ADD;
            `OP_SW:
                aluop = `ALU_ADD;
            `OP_BEQ:
                aluop = `ALU_ADD;
            default:
                aluop = `ALU_ADD;
        end
    end
endmodule;
