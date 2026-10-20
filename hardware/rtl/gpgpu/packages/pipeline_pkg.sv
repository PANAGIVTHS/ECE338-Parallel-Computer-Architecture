package pipeline_pkg;

    //! Forwarding select signals ForwardingUnit/StreamingProcessor
    typedef enum logic [1:0] {
        NO_DEP = 2'b00,
        MEMWB_EXALU_DEP = 2'b01,
        EXALU_MEMALU_DEP = 2'b10
    } forward_sel_t;

    //! SM -> SP ID/EX signals
    typedef struct packed {
        gpu_pkg::pc_t program_counter;
        riscv_pkg::opcode_t opcode;
        riscv_pkg::instr_type_t instr_type;
        alu_pkg::alu_op_t alu_op;
        gpu_pkg::reg_addr_t rs1;
        gpu_pkg::reg_addr_t rs2;
        gpu_pkg::reg_addr_t rd;
        logic [19:0] imm_31_12;
        logic [11:0] imm_31_20;
        logic [6:0] imm_31_25;
        logic [2:0] funct3;
        logic wen;
    } id_ex_t;

    typedef struct packed {
        logic valid;
        gpu_pkg::reg_addr_t rd;
    } mul_hazard_t;

    typedef struct packed {
        gpu_pkg::pc_t program_counter;
        mul_hazard_t hazard;
    } mul_stage_t; 

    typedef struct packed {
        gpu_pkg::word_t alu_out;
        gpu_pkg::word_t reg_b;
        gpu_pkg::word_t program_counter;
        riscv_pkg::opcode_t opcode;
        gpu_pkg::reg_addr_t rd;
        logic mul3_valid;
        logic wen;
        logic core_complete;
    } ex_mem_t;

    typedef struct packed {
        gpu_pkg::reg_addr_t rd;
        logic is_mul;
        logic is_load;
        gpu_pkg::word_t alu_out;
        logic wen;
        gpu_pkg::pc_t program_counter;
    } mem_wb_t;

    //! SP -> SM feedback signals
    typedef struct packed {
        logic branch_taken;
        gpu_pkg::imem_idx_t branch_target_idx;
        mul_hazard_t mul1;
        mul_hazard_t mul2;
        mul_hazard_t mul3;
    } sp_feedback_t;

endpackage
