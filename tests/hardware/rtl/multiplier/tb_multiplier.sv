`timescale 1ns/1ps

module tb_multiplier;
    import gpu_pkg::*;
    import riscv_pkg::*;
    import alu_pkg::*;
    import pipeline_pkg::*;

    parameter int unsigned LATENCY = 3;
    logic clk = 0;
    logic rst = 0, stall = 0;
    word_t a, b, result, alu_result;
    mul_stage_t stage_in, stage_out;
    mul_hazard_t hazards [0:LATENCY-1];
    word_t expected_result [0:LATENCY-1];
    mul_stage_t expected_stage [0:LATENCY-1];
    alu_op_t op;
    logic select_mul, zero;
    reg_addr_t rs1, rs2, ex_rd;
    logic ex_load, ex_mul, id_mul, branch_taken, hazard, flush;
    instr_type_t instr_type;
    mul_hazard_t hazard_inputs [0:LATENCY-1];
    logic [31:0] seed = 32'h338abcde;

    always #5 clk = ~clk;

    Multiplier #(.LATENCY(LATENCY)) dut (
        .clk(clk), .rst(rst), .i_operand_a(a), .i_operand_b(b),
        .i_global_stall(stall), .i_stage(stage_in),
        .o_result(result), .o_stage(stage_out), .o_hazards(hazards)
    );
    ALU alu (
        .i_operand_a(a), .i_operand_b(b), .i_alu_op(op),
        .i_mul_valid(select_mul), .i_mul_res(result),
        .o_alu_out(alu_result), .o_alu_zero(zero)
    );
    HazardUnit #(.MUL_LATENCY(LATENCY)) hazard_dut (
        .i_id_rs1(rs1), .i_id_rs2(rs2), .i_idex_rd(ex_rd),
        .i_ex_is_load(ex_load), .i_ex_is_mul(ex_mul), .i_id_is_mul(id_mul),
        .i_mul(hazard_inputs), .i_id_instr_type(instr_type),
        .i_branch_taken(branch_taken), .o_data_hazard(hazard), .o_flush(flush)
    );

    function automatic logic [31:0] random_word();
        seed ^= seed << 13;
        seed ^= seed >> 17;
        seed ^= seed << 5;
        return seed;
    endfunction

    function automatic word_t normal_alu();
        case (op)
            ALU_OP_ADD: return a + b;
            ALU_OP_SUB: return a - b;
            ALU_OP_AND: return a & b;
            ALU_OP_OR: return a | b;
            ALU_OP_XOR: return a ^ b;
            ALU_OP_SLL: return a << b[4:0];
            ALU_OP_SRA: return $signed(a) >>> b[4:0];
            ALU_OP_SRL: return a >> b[4:0];
            ALU_OP_SLT: return word_t'($signed(a) < $signed(b));
            ALU_OP_SLTU: return word_t'(a < b);
            ALU_OP_LUI: return b;
            default: return '0;
        endcase
    endfunction

    task automatic tick();
        @(posedge clk);
        if (!rst) begin
            for (int s = 0; s < LATENCY; s++) begin
                expected_result[s] = '0;
                expected_stage[s] = '0;
            end
        end else if (!stall) begin
            for (int s = LATENCY-1; s > 0; s--) begin
                expected_result[s] = expected_result[s-1];
                expected_stage[s] = expected_stage[s-1];
            end
            expected_result[0] = a * b;
            expected_stage[0] = stage_in;
        end
        #1;
        assert (result === expected_result[LATENCY-1]) else $fatal(1, "Result/latency mismatch");
        assert (stage_out === expected_stage[LATENCY-1]) else $fatal(1, "rd/PC/valid mismatch");
        for (int s = 0; s < LATENCY; s++) begin
            assert (hazards[s] === expected_stage[s].hazard) else $fatal(1, "Hazard stage %0d mismatch", s);
        end
    endtask

    task automatic check_alu();
        word_t expected;
        #1;
        expected = select_mul ? result : normal_alu();
        assert (alu_result === expected && zero === (expected == '0)) else $fatal(1, "ALU op %0d mismatch", op);
    endtask

    task automatic check_hazard();
        logic pending, independent, expected_hazard, expected_flush;
        pending = ex_mul;
        // Preserve the original EX-rd check even when ex_mul is false.
        independent = id_mul && rs1 != ex_rd && rs2 != ex_rd;
        for (int s = 0; s < LATENCY; s++) begin
            pending |= hazard_inputs[s].valid;
            independent &= !hazard_inputs[s].valid ||
                (rs1 != hazard_inputs[s].rd && rs2 != hazard_inputs[s].rd);
        end
        expected_hazard = 0;
        expected_flush = 0;
        if (ex_load && ex_rd != '0) begin
            expected_hazard = rs1 == ex_rd || (instr_type != INSTR_TYPE_I && rs2 == ex_rd);
        end else if (branch_taken) begin
            expected_hazard = 1;
            expected_flush = 1;
        end else if (pending && !independent) begin
            expected_hazard = 1;
        end
        #1;
        assert (hazard === expected_hazard && flush === expected_flush) else $fatal(1, "Hazard policy mismatch");
    endtask

    initial begin
        a = 0; b = 0; stage_in = '0; op = ALU_OP_ADD; select_mul = 0;
        tick();
        @(negedge clk);
        rst = 1;
        // Back-to-back valid products with different destinations and PCs.
        for (int n = 0; n < 3*LATENCY+4; n++) begin
            a = 32'hffff_ffff - word_t'(n);
            b = 32'h8000_0000 + word_t'(n);
            stage_in = '{program_counter: pc_t'(4*n), hazard: '{valid: 1'b1, rd: reg_addr_t'(n%30+1)}};
            tick();
            @(negedge clk);
        end
        // Freeze with valid entries in flight, then reset while still stalled.
        stall = 1;
        repeat (4) begin
            a = random_word(); b = random_word(); stage_in = '0;
            tick(); @(negedge clk);
        end
        rst = 0;
        tick(); @(negedge clk);
        rst = 1; stall = 0;
        // Bubbles, x0 metadata, resets, stalls, signed bit patterns, and truncation.
        for (int n = 0; n < 2000; n++) begin
            a = random_word(); b = random_word();
            stage_in.program_counter = pc_t'(random_word());
            stage_in.hazard.rd = reg_addr_t'(random_word());
            stage_in.hazard.valid = (n%3 != 0) && stage_in.hazard.rd != '0;
            stall = (n%7 < 2);
            rst = (n%137 != 0);
            op = alu_op_t'(n%16);
            select_mul = (n%5 == 0);
            tick();
            check_alu();
            @(negedge clk);
        end
        rst = 1; stall = 0; stage_in = '0;
        repeat (LATENCY+1) begin tick(); @(negedge clk); end
        // Exercise all ALU selects with zero, sign, overflow and shift-boundary inputs.
        for (int n = 0; n < 256; n++) begin
            a = (n%4 == 0) ? 0 : (n%4 == 1) ? 32'h8000_0000 : random_word();
            b = (n%3 == 0) ? a : random_word();
            op = alu_op_t'(n%16); select_mul = 0;
            check_alu();
        end
        ex_load = 0; ex_mul = 0; ex_rd = 31; id_mul = 1;
        branch_taken = 0; instr_type = INSTR_TYPE_R; rs1 = 1; rs2 = 2;
        for (int s = 0; s < LATENCY; s++) hazard_inputs[s] = '0;
        // Each registered stage must independently block a dependent MUL and any non-MUL.
        for (int s = 0; s < LATENCY; s++) begin
            hazard_inputs[s] = '{valid: 1'b1, rd: 5'd7};
            check_hazard();
            assert (!hazard) else $fatal(1, "Independent MUL blocked");
            rs1 = 7; check_hazard();
            assert (hazard) else $fatal(1, "Dependent MUL allowed");
            rs1 = 1; rs2 = 7; check_hazard();
            assert (hazard) else $fatal(1, "rs2 dependency missed");
            rs2 = 2; id_mul = 0; check_hazard();
            assert (hazard) else $fatal(1, "Non-MUL allowed while pending");
            id_mul = 1; hazard_inputs[s] = '0;
        end
        for (int n = 0; n < 10000; n++) begin
            rs1 = reg_addr_t'(random_word()); rs2 = reg_addr_t'(random_word());
            ex_rd = reg_addr_t'(random_word());
            ex_load = (n%5 == 0); ex_mul = (n%3 == 0);
            id_mul = (n%2 == 0); branch_taken = (n%7 == 0);
            instr_type = instr_type_t'(n%4);
            for (int s = 0; s < LATENCY; s++) begin
                hazard_inputs[s] = mul_hazard_t'(random_word());
            end
            check_hazard();
        end
        $display("PASS multiplier/ALU/hazard LATENCY=%0d", LATENCY);
        $finish;
    end
endmodule
