package riscv_pkg;

    localparam logic [2:0] FUNCT3_ADD_SUB_MUL = 3'b000;
    localparam logic [2:0] FUNCT3_BEQ = 3'b000;
    localparam logic [2:0] FUNCT3_BNE = 3'b001;
    localparam logic [2:0] FUNCT3_BLT = 3'b100;
    localparam logic [2:0] FUNCT3_BGE = 3'b101;
    localparam logic [2:0] FUNCT3_BLTU = 3'b110;
    localparam logic [2:0] FUNCT3_BGEU = 3'b111;
    localparam logic [2:0] FUNCT3_MEM = 3'b010;
    localparam logic [2:0] FUNCT3_DIV = 3'b100;
    localparam logic [2:0] FUNCT3_SLL = 3'b001;
    localparam logic [2:0] FUNCT3_SRA = 3'b101;
    localparam logic [2:0] FUNCT3_XOR = 3'b100;
    localparam logic [2:0] FUNCT3_OR = 3'b110;
    localparam logic [2:0] FUNCT3_AND = 3'b111;
    localparam logic [2:0] FUNCT3_SLT = 3'b010;
    localparam logic [2:0] FUNCT3_SLTU = 3'b011;
    localparam logic [2:0] FUNCT3_SRL = 3'b101;

    localparam logic [6:0] FUNCT7_ADD = 7'b0000000;
    localparam logic [6:0] FUNCT7_SUB = 7'b0100000;
    localparam logic [6:0] FUNCT7_MULDIV = 7'b0000001;

    //! Opcode field (bits [6:0])
    typedef enum logic [6:0] {
        OP_R_TYPE = 7'b0110011,
        OP_LW = 7'b0000011,
        OP_SW = 7'b0100011,
        OP_BEQ = 7'b1100011,
        OP_ADDI = 7'b0010011,
        OP_JAL = 7'b1101111,
        OP_JALR = 7'b1100111,
        OP_LUI = 7'b0110111,
        OP_INVALID = 7'b0
    } opcode_t;

    //! Instruction categorization
    typedef enum logic [1:0] {
        INSTR_TYPE_R = 2'b00,
        INSTR_TYPE_I = 2'b01,
        INSTR_TYPE_S = 2'b10,
        INSTR_TYPE_U = 2'b11
    } instr_type_t;

endpackage
