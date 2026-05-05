`define OP_R_TYPE 7'b0110011
`define OP_LW     7'b0000011
`define OP_SW     7'b0100011
`define OP_BEQ    7'b1100011
`define OP_ADDI   7'b0010011

`define FUNCT3_ADD_SUB_MUL 3'b000
`define FUNCT3_MEM 3'b010
`define FUNCT3_DIV 3'b100

`define FUNCT7_ADD 7'b0000000
`define FUNCT7_SUB 7'b0100000
`define FUNCT7_MULDIV 7'b0000001

`define ALU_ADD 2'b00
`define ALU_SUB 2'b01
`define ALU_MUL 2'b10
`define ALU_DIV 2'b11

`define INSTR_TYPE_R 2'b00
`define INSTR_TYPE_I 2'b01
`define INSTR_TYPE_S 2'b10

`define EXALU_MEMALU_DEP 2'b10
`define MEMWB_EXALU_DEP 2'b01
`define NO_DEP 2'b00

`define INITIAL_PC 32'hFFFFFFFC
`define IMEM_ENTRIES 1024

`define NOP_INSTR 32'h00000013
