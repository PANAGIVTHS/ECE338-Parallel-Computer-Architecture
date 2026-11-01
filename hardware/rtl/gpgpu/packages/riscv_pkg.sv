package riscv_pkg;

    localparam logic [31:0] ECALL_INSTR = 32'h0000_0073;
    localparam gpu_pkg::reg_addr_t ECALL_SERVICE_REGISTER = 5'd17;

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
        OP_SYSTEM = 7'b1110011,
        OP_INVALID = 7'b0
    } opcode_t;

    //! Instruction categorization
    typedef enum logic [1:0] {
        INSTR_TYPE_R = 2'b00,
        INSTR_TYPE_I = 2'b01,
        INSTR_TYPE_S = 2'b10,
        INSTR_TYPE_U = 2'b11
    } instr_type_t;

    //! Encoded instruction layouts. Packed order follows the instruction word.
    localparam int unsigned IMM_I_W = 12;
    localparam int unsigned IMM_U_W = gpu_pkg::XLEN - IMM_I_W;
    typedef logic [2:0] funct3_t;
    typedef logic [6:0] funct7_t;
    typedef logic [IMM_I_W-1:0] imm12_t;
    typedef logic [IMM_U_W-1:0] imm20_t;

    typedef struct packed {
        funct7_t funct7;
        gpu_pkg::reg_addr_t rs2;
        gpu_pkg::reg_addr_t rs1;
        funct3_t funct3;
        gpu_pkg::reg_addr_t rd;
        opcode_t opcode;
    } instruction_r_t;

    typedef struct packed {
        imm12_t imm;
        gpu_pkg::reg_addr_t rs1;
        funct3_t funct3;
        gpu_pkg::reg_addr_t rd;
        opcode_t opcode;
    } instruction_i_t;

    typedef struct packed {
        funct7_t imm_hi;
        gpu_pkg::reg_addr_t rs2;
        gpu_pkg::reg_addr_t rs1;
        funct3_t funct3;
        logic [4:0] imm_lo;
        opcode_t opcode;
    } instruction_s_t;

    typedef struct packed {
        logic imm_12;
        logic [5:0] imm_10_5;
        gpu_pkg::reg_addr_t rs2;
        gpu_pkg::reg_addr_t rs1;
        funct3_t funct3;
        logic [3:0] imm_4_1;
        logic imm_11;
        opcode_t opcode;
    } instruction_b_t;

    typedef struct packed {
        imm20_t imm;
        gpu_pkg::reg_addr_t rd;
        opcode_t opcode;
    } instruction_u_t;

    typedef struct packed {
        logic imm_20;
        logic [9:0] imm_10_1;
        logic imm_11;
        logic [7:0] imm_19_12;
        gpu_pkg::reg_addr_t rd;
        opcode_t opcode;
    } instruction_j_t;

    typedef union packed {
        gpu_pkg::word_t bits;
        instruction_r_t r;
        instruction_i_t i;
        instruction_s_t s;
        instruction_b_t b;
        instruction_u_t u;
        instruction_j_t j;
    } instruction_t;

    function automatic gpu_pkg::word_t immediate_i(imm12_t immediate);
        return gpu_pkg::word_t'($signed(immediate));
    endfunction

    function automatic gpu_pkg::word_t immediate_s(funct7_t upper, gpu_pkg::reg_addr_t lower);
        return immediate_i({upper, lower});
    endfunction

    function automatic gpu_pkg::word_t immediate_u(imm20_t immediate);
        return {immediate, {IMM_I_W{1'b0}}};
    endfunction

    function automatic gpu_pkg::word_t immediate_b(funct7_t upper, gpu_pkg::reg_addr_t lower);
        instruction_t encoding;
        logic [12:0] displacement;
        encoding = '0;
        encoding.r.funct7 = upper;
        encoding.r.rd = lower;
        displacement = {encoding.b.imm_12, encoding.b.imm_11,
                        encoding.b.imm_10_5, encoding.b.imm_4_1, 1'b0};
        return gpu_pkg::word_t'($signed(displacement));
    endfunction

    function automatic gpu_pkg::word_t immediate_j(imm20_t immediate);
        instruction_t encoding;
        logic [20:0] displacement;
        encoding = '0;
        encoding.u.imm = immediate;
        displacement = {encoding.j.imm_20, encoding.j.imm_19_12,
                        encoding.j.imm_11, encoding.j.imm_10_1, 1'b0};
        return gpu_pkg::word_t'($signed(displacement));
    endfunction

endpackage
