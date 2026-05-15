`define OP_R_TYPE 7'b0110011
`define OP_LW     7'b0000011
`define OP_SW     7'b0100011
`define OP_BEQ    7'b1100011
`define OP_ADDI   7'b0010011
`define OP_JALR   7'b1100111

`define FUNCT3_ADD_SUB_MUL 3'b000
`define FUNCT3_MEM 3'b010
`define FUNCT3_DIV 3'b100
`define FUNCT3_SLL 3'b001
`define FUNCT3_SRA 3'b101
`define FUNCT3_OR  3'b110
`define FUNCT3_AND 3'b111
`define FUNCT3_SLT  3'b010
`define FUNCT3_SLTU 3'b011
`define FUNCT3_SRL  3'b101

`define FUNCT7_ADD 7'b0000000
`define FUNCT7_SUB 7'b0100000
`define FUNCT7_MULDIV 7'b0000001

`define ALU_ADD 4'b0000
`define ALU_SUB 4'b0001
`define ALU_MUL 4'b0010
`define ALU_DIV 4'b0011
`define ALU_AND 4'b0100
`define ALU_OR  4'b0101
`define ALU_SLL 4'b0110
`define ALU_SRA 4'b0111
`define ALU_SRL 4'b1000
`define ALU_SLT 4'b1001
`define ALU_SLTU 4'b1010

`define INSTR_TYPE_R 2'b00
`define INSTR_TYPE_I 2'b01
`define INSTR_TYPE_S 2'b10

`define EXALU_MEMALU_DEP 2'b10
`define MEMWB_EXALU_DEP 2'b01
`define NO_DEP 2'b00

`define INITIAL_PC 32'hFFFFFFFC
`define IMEM_ENTRIES 2048
`define DMEM_ENTRIES 2048

`define NOP_INSTR 32'h00000013
`define TXD_REGISTER 5'h1F
`define STACK_P_INIT 0
