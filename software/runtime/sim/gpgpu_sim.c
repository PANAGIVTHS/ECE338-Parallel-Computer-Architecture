/* Functional simulator of the GPGPU (gpgpu_sim.h). It follows
 * tools/tests/gpgpu_model.py rule for rule; `gpgpu software runtime:check`
 * compares the two on every RTL case. */
#include "gpgpu_sim.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "gpgpu_hw.h"

#define REGS 32u
#define MAX_LANES 64u

struct gpgpu_sim {
    gpgpu_sim_config_t c;
    uint32_t *imem;
    uint32_t *dmem;
    uint8_t *ddr;
    uint32_t ddr_low, ddr_high;
    uint8_t *touched;
    uint32_t regs[MAX_LANES][REGS];
};

gpgpu_sim_config_t gpgpu_sim_default_config(void)
{
    gpgpu_sim_config_t c = {
        .lanes = GPGPU_HW_NUM_CORES,
        .imem_words = GPGPU_HW_IMEM_ENTRIES,
        .dmem_words = GPGPU_HW_DMEM_ENTRIES,
        .dmem_base = GPGPU_HW_DMEM_BASE,
        .fb0_base = GPGPU_HW_FB0_BASE,
        .fb1_base = GPGPU_HW_FB1_BASE,
        .fb_size = GPGPU_HW_FB_SIZE,
        .gmem_base = GPGPU_HW_GMEM_BASE,
        .gmem_size = GPGPU_HW_GMEM_SIZE,
        .stack_p_init = GPGPU_HW_STACK_P_INIT,
        .txd_register = GPGPU_HW_TXD_REGISTER,
        .group_bytes = GPGPU_HW_GROUP_BYTES,
        .beat_lsb = GPGPU_HW_BEAT_LSB,
        .ddr_enable = GPGPU_HW_DDR_ENABLE,
        .st_ok = GPGPU_HW_ST_OK,
        .st_unmapped = GPGPU_HW_ST_UNMAPPED,
        .st_permission = GPGPU_HW_ST_PERMISSION,
        .st_misaligned = GPGPU_HW_ST_MISALIGNED,
    };
    return c;
}

static uint32_t min_u32(uint32_t a, uint32_t b) { return a < b ? a : b; }
static uint32_t max_u32(uint32_t a, uint32_t b) { return a > b ? a : b; }

void gpgpu_sim_ddr_bounds(const gpgpu_sim_config_t *c, uint32_t *low, uint32_t *high)
{
    *low = min_u32(min_u32(c->fb0_base, c->fb1_base), c->gmem_base);
    *high = max_u32(max_u32(c->fb0_base + c->fb_size, c->fb1_base + c->fb_size), c->gmem_base + c->gmem_size);
}

gpgpu_sim_t *gpgpu_sim_create(const gpgpu_sim_config_t *config, uint8_t *ddr, uint32_t ddr_low, uint32_t ddr_high,
                              uint8_t *touched)
{
    if (config->lanes == 0 || config->lanes > MAX_LANES || config->txd_register >= REGS)
        return NULL;
    gpgpu_sim_t *sim = calloc(1, sizeof *sim);
    if (sim == NULL)
        return NULL;
    sim->c = *config;
    sim->imem = calloc(config->imem_words, sizeof *sim->imem);
    sim->dmem = calloc(config->dmem_words, sizeof *sim->dmem);
    if (sim->imem == NULL || sim->dmem == NULL) {
        gpgpu_sim_destroy(sim);
        return NULL;
    }
    sim->ddr = ddr;
    sim->ddr_low = ddr_low;
    sim->ddr_high = ddr_high;
    sim->touched = touched;
    return sim;
}

void gpgpu_sim_destroy(gpgpu_sim_t *sim)
{
    if (sim == NULL)
        return;
    free(sim->imem);
    free(sim->dmem);
    free(sim);
}

const gpgpu_sim_config_t *gpgpu_sim_config(const gpgpu_sim_t *sim) { return &sim->c; }
uint32_t *gpgpu_sim_imem(gpgpu_sim_t *sim) { return sim->imem; }
uint32_t *gpgpu_sim_dmem(gpgpu_sim_t *sim) { return sim->dmem; }

uint32_t gpgpu_sim_register(const gpgpu_sim_t *sim, uint32_t lane, uint32_t index)
{
    return lane < sim->c.lanes && index < REGS ? sim->regs[lane][index] : 0;
}

/* ---- Decode ------------------------------------------------------------ */

typedef enum {
    OP_INVALID,
    OP_ADD, OP_SUB, OP_MUL, OP_SLL, OP_SLT, OP_SLTU, OP_XOR, OP_SRL, OP_SRA, OP_OR, OP_AND,
    OP_ADDI, OP_SLTI, OP_SLTIU, OP_XORI, OP_ORI, OP_ANDI, OP_SLLI, OP_SRLI, OP_SRAI,
    OP_LUI, OP_AUIPC,
    OP_LB, OP_LH, OP_LW, OP_LBU, OP_LHU,
    OP_SB, OP_SH, OP_SW,
    OP_BEQ, OP_BNE, OP_BLT, OP_BGE, OP_BLTU, OP_BGEU,
    OP_JAL, OP_JALR, OP_ECALL
} op_t;

typedef struct {
    op_t op;
    uint32_t rd, rs1, rs2;
    int32_t imm;
} inst_t;

static int32_t sext(uint32_t value, unsigned bits)
{
    uint32_t mask = bits >= 32 ? 0xFFFFFFFFu : (1u << bits) - 1u;
    value &= mask;
    return (value >> (bits - 1)) & 1u ? (int32_t)(value | ~mask) : (int32_t)value;
}

static inst_t decode(uint32_t w)
{
    inst_t i = {OP_INVALID, (w >> 7) & 31u, (w >> 15) & 31u, (w >> 20) & 31u, 0};
    uint32_t opcode = w & 0x7Fu, f3 = (w >> 12) & 7u, f7 = w >> 25;

    switch (opcode) {
    case 0x33:
        if (f7 == 0x00) {
            static const op_t r[8] = {OP_ADD, OP_SLL, OP_SLT, OP_SLTU, OP_XOR, OP_SRL, OP_OR, OP_AND};
            i.op = r[f3];
        } else if (f7 == 0x20 && f3 == 0) {
            i.op = OP_SUB;
        } else if (f7 == 0x20 && f3 == 5) {
            i.op = OP_SRA;
        } else if (f7 == 0x01 && f3 == 0) {
            i.op = OP_MUL;
        }
        break;
    case 0x13:
        i.imm = sext(w >> 20, 12);
        switch (f3) {
        case 0: i.op = OP_ADDI; break;
        case 2: i.op = OP_SLTI; break;
        case 3: i.op = OP_SLTIU; break;
        case 4: i.op = OP_XORI; break;
        case 6: i.op = OP_ORI; break;
        case 7: i.op = OP_ANDI; break;
        case 1:
            if (f7 == 0x00) { i.op = OP_SLLI; i.imm = (int32_t)i.rs2; }
            break;
        case 5:
            if (f7 == 0x00) { i.op = OP_SRLI; i.imm = (int32_t)i.rs2; }
            else if (f7 == 0x20) { i.op = OP_SRAI; i.imm = (int32_t)i.rs2; }
            break;
        }
        break;
    case 0x37: i.op = OP_LUI; i.imm = (int32_t)(w & 0xFFFFF000u); break;
    case 0x17: i.op = OP_AUIPC; i.imm = (int32_t)(w & 0xFFFFF000u); break;
    case 0x03:
        i.imm = sext(w >> 20, 12);
        switch (f3) {
        case 0: i.op = OP_LB; break;
        case 1: i.op = OP_LH; break;
        case 2: i.op = OP_LW; break;
        case 4: i.op = OP_LBU; break;
        case 5: i.op = OP_LHU; break;
        }
        break;
    case 0x23:
        i.imm = sext((f7 << 5) | ((w >> 7) & 31u), 12);
        switch (f3) {
        case 0: i.op = OP_SB; break;
        case 1: i.op = OP_SH; break;
        case 2: i.op = OP_SW; break;
        }
        break;
    case 0x63: {
        uint32_t offset = (((w >> 31) & 1u) << 12) | (((w >> 7) & 1u) << 11) | (((w >> 25) & 0x3Fu) << 5) |
                          (((w >> 8) & 0xFu) << 1);
        static const op_t b[8] = {OP_BEQ, OP_BNE, OP_INVALID, OP_INVALID, OP_BLT, OP_BGE, OP_BLTU, OP_BGEU};
        i.op = b[f3];
        i.imm = sext(offset, 13);
        break;
    }
    case 0x6F: {
        uint32_t offset = (((w >> 31) & 1u) << 20) | (((w >> 12) & 0xFFu) << 12) | (((w >> 20) & 1u) << 11) |
                          (((w >> 21) & 0x3FFu) << 1);
        i.op = OP_JAL;
        i.imm = sext(offset, 21);
        break;
    }
    case 0x67:
        if (f3 == 0) { i.op = OP_JALR; i.imm = sext(w >> 20, 12); }
        break;
    default:
        if (w == 0x00000073u)
            i.op = OP_ECALL;
        break;
    }
    return i;
}

/* ---- Memory ------------------------------------------------------------ */

typedef enum { TGT_NONE, TGT_DMEM, TGT_DDR } target_t;

static int in_range(uint32_t addr, uint32_t base, uint32_t size)
{
    return addr >= base && addr - base < size;
}

/* MemorySubsystemPkg::decode_access */
static target_t decode_access(const gpgpu_sim_config_t *c, uint32_t addr, uint32_t size, int write,
                              uint32_t *status)
{
    *status = c->st_ok;
    if (addr & (size - 1u)) {
        *status = c->st_misaligned;
        return TGT_NONE;
    }
    if (in_range(addr, c->dmem_base, 4u * c->dmem_words))
        return TGT_DMEM;
    target_t target;
    if (in_range(addr, c->fb0_base, c->fb_size) || in_range(addr, c->fb1_base, c->fb_size)) {
        if (!write) {
            *status = c->st_permission;
            return TGT_NONE;
        }
        target = TGT_DDR;
    } else if (in_range(addr, c->gmem_base, c->gmem_size)) {
        target = TGT_DDR;
    } else {
        *status = c->st_unmapped;
        return TGT_NONE;
    }
    if (!c->ddr_enable) {
        *status = c->st_unmapped;
        return TGT_NONE;
    }
    return target;
}

static uint32_t *word_at(gpgpu_sim_t *sim, target_t target, uint32_t addr)
{
    if (target == TGT_DMEM)
        return &sim->dmem[(addr - sim->c.dmem_base) >> 2];
    return (uint32_t *)(void *)(sim->ddr + ((addr & ~3u) - sim->ddr_low));
}

static uint32_t load_value(op_t op, uint32_t word, uint32_t addr)
{
    uint32_t shift = (addr & 3u) * 8u;
    switch (op) {
    case OP_LB: return (uint32_t)sext(word >> shift, 8);
    case OP_LBU: return (word >> shift) & 0xFFu;
    case OP_LH: return (uint32_t)sext(word >> shift, 16);
    case OP_LHU: return (word >> shift) & 0xFFFFu;
    default: return word;
    }
}

static uint32_t access_bytes(op_t op)
{
    switch (op) {
    case OP_LB: case OP_LBU: case OP_SB: return 1;
    case OP_LH: case OP_LHU: case OP_SH: return 2;
    default: return 4;
    }
}

/* ---- Execution --------------------------------------------------------- */

static int branch_taken(op_t op, uint32_t a, uint32_t b)
{
    switch (op) {
    case OP_BEQ: return a == b;
    case OP_BNE: return a != b;
    case OP_BLT: return (int32_t)a < (int32_t)b;
    case OP_BGE: return (int32_t)a >= (int32_t)b;
    case OP_BLTU: return a < b;
    default: return a >= b;
    }
}

static uint32_t alu(op_t op, uint32_t a, uint32_t b)
{
    switch (op) {
    case OP_ADD: case OP_ADDI: return a + b;
    case OP_SUB: return a - b;
    case OP_MUL: return a * b;
    case OP_AND: case OP_ANDI: return a & b;
    case OP_OR: case OP_ORI: return a | b;
    case OP_XOR: case OP_XORI: return a ^ b;
    case OP_SLL: case OP_SLLI: return a << (b & 31u);
    case OP_SRL: case OP_SRLI: return a >> (b & 31u);
    case OP_SRA: case OP_SRAI: return (uint32_t)((int32_t)a >> (b & 31u));
    case OP_SLT: case OP_SLTI: return (int32_t)a < (int32_t)b;
    default: return a < b; /* SLTU, SLTIU */
    }
}

static int is_immediate(op_t op)
{
    return op >= OP_ADDI && op <= OP_SRAI;
}

static void set_reg(gpgpu_sim_t *sim, uint32_t lane, uint32_t rd, uint32_t value)
{
    if (rd != 0 && rd != sim->c.txd_register)
        sim->regs[lane][rd] = value;
}

/* A DDR byte stored by one instruction: the ambiguity check and the bursts. */
typedef struct {
    uint32_t addr;
    uint8_t value;
} stored_byte_t;

static void reset(gpgpu_sim_t *sim)
{
    memset(sim->regs, 0, sizeof sim->regs);
    for (uint32_t lane = 0; lane < sim->c.lanes; lane++) {
        sim->regs[lane][2] = sim->c.stack_p_init;
        sim->regs[lane][sim->c.txd_register] = lane;
    }
}

void gpgpu_sim_run(gpgpu_sim_t *sim, uint64_t max_instructions, gpgpu_sim_divergence_fn divergence,
                   gpgpu_sim_stop_fn stop, void *context, gpgpu_sim_result_t *r)
{
    const gpgpu_sim_config_t *c = &sim->c;
    const uint32_t lanes = c->lanes;
    uint32_t pc = 0; /* instruction index */

    memset(r, 0, sizeof *r);
    reset(sim);
    for (;;) {
        if (r->instructions >= max_instructions || (stop != NULL && (r->instructions & 0xFFFFu) == 0 && r->instructions != 0 &&
                                                     stop(context))) {
            r->status = GPGPU_SIM_LIMIT;
            snprintf(r->error, sizeof r->error, "stopped after %llu instructions (PC 0x%x)",
                     (unsigned long long)r->instructions, pc * 4u);
            return;
        }
        uint32_t word = sim->imem[pc];
        inst_t in = decode(word);
        uint32_t pc_bytes = pc * 4u;
        uint32_t next = (pc + 1u) % c->imem_words;

        if (in.op == OP_INVALID) {
            r->status = GPGPU_SIM_ERROR;
            snprintf(r->error, sizeof r->error, "PC 0x%x: unsupported instruction %08x", pc_bytes, word);
            return;
        }
        r->instructions++;

        switch (in.op) {
        case OP_ECALL: {
            /* Lane 0 decides, like a branch: service 0 (a7 = 0) completes. */
            for (uint32_t lane = 1; lane < lanes; lane++)
                if (sim->regs[lane][17] != sim->regs[0][17]) {
                    if (divergence != NULL)
                        divergence(context, pc_bytes);
                    break;
                }
            if (sim->regs[0][17] == 0) {
                r->status = GPGPU_SIM_DONE;
                return;
            }
            break;
        }
        case OP_BEQ: case OP_BNE: case OP_BLT: case OP_BGE: case OP_BLTU: case OP_BGEU: {
            int taken = branch_taken(in.op, sim->regs[0][in.rs1], sim->regs[0][in.rs2]);
            for (uint32_t lane = 1; lane < lanes; lane++)
                if (branch_taken(in.op, sim->regs[lane][in.rs1], sim->regs[lane][in.rs2]) != taken) {
                    if (divergence != NULL)
                        divergence(context, pc_bytes);
                    break;
                }
            if (taken)
                next = (uint32_t)((int64_t)pc + in.imm / 4) % c->imem_words;
            break;
        }
        case OP_JAL:
            for (uint32_t lane = 0; lane < lanes; lane++)
                set_reg(sim, lane, in.rd, pc_bytes + 4u);
            next = (uint32_t)((int64_t)pc + in.imm / 4) % c->imem_words;
            break;
        case OP_JALR: {
            uint32_t target = (sim->regs[0][in.rs1] + (uint32_t)in.imm) & ~1u;
            for (uint32_t lane = 0; lane < lanes; lane++)
                set_reg(sim, lane, in.rd, pc_bytes + 4u);
            next = (target >> 2) % c->imem_words;
            break;
        }
        case OP_LUI:
            for (uint32_t lane = 0; lane < lanes; lane++)
                set_reg(sim, lane, in.rd, (uint32_t)in.imm);
            break;
        case OP_AUIPC:
            for (uint32_t lane = 0; lane < lanes; lane++)
                set_reg(sim, lane, in.rd, pc_bytes + (uint32_t)in.imm);
            break;
        case OP_LB: case OP_LH: case OP_LW: case OP_LBU: case OP_LHU:
        case OP_SB: case OP_SH: case OP_SW: {
            const int write = in.op == OP_SB || in.op == OP_SH || in.op == OP_SW;
            const uint32_t size = access_bytes(in.op);
            uint32_t addrs[MAX_LANES];
            target_t targets[MAX_LANES];
            uint32_t bad = 0, kinds = 0;
            for (uint32_t lane = 0; lane < lanes; lane++) {
                uint32_t status;
                addrs[lane] = sim->regs[lane][in.rs1] + (uint32_t)in.imm;
                targets[lane] = decode_access(c, addrs[lane], size, write, &status);
                if (targets[lane] == TGT_DMEM)
                    r->dmem_lane_accesses++;
                if (status != c->st_ok) {
                    bad |= 1u << lane;
                    kinds |= 1u << (status - 1u);
                }
            }
            if (bad != 0) {
                r->status = GPGPU_SIM_FAULT;
                r->fault_pc = pc_bytes;
                r->fault_lanes = bad;
                r->fault_kinds = kinds;
                return;
            }
            if (write) {
                stored_byte_t bytes[MAX_LANES * 4];
                uint32_t stored = 0;
                for (uint32_t lane = 0; lane < lanes; lane++) { /* ascending: the highest lane's store survives */
                    uint32_t value = sim->regs[lane][in.rs2];
                    uint32_t shift = (addrs[lane] & 3u) * 8u;
                    uint32_t mask = (size == 4 ? 0xFFFFFFFFu : ((1u << (size * 8u)) - 1u)) << shift;
                    uint32_t *slot = word_at(sim, targets[lane], addrs[lane]);
                    if (targets[lane] == TGT_DDR) {
                        r->ddr_lane_stores++;
                        for (uint32_t b = 0; b < size; b++)
                            bytes[stored++] = (stored_byte_t){addrs[lane] + b, (uint8_t)(value >> (8u * b))};
                        if (sim->touched != NULL) {
                            uint32_t index = ((addrs[lane] & ~3u) - sim->ddr_low) >> 2;
                            sim->touched[index >> 3] |= (uint8_t)(1u << (index & 7u));
                        }
                    }
                    *slot = (*slot & ~mask) | ((value << shift) & mask);
                }
                uint32_t groups[MAX_LANES * 4], group_count = 0, lowest_conflict = 0;
                int conflict = 0;
                for (uint32_t i = 0; i < stored; i++) {
                    for (uint32_t j = 0; j < i; j++)
                        if (bytes[j].addr == bytes[i].addr && bytes[j].value != bytes[i].value &&
                            (!conflict || bytes[i].addr < lowest_conflict)) {
                            conflict = 1;
                            lowest_conflict = bytes[i].addr;
                        }
                    uint32_t group = bytes[i].addr / c->group_bytes, g = 0;
                    while (g < group_count && groups[g] != group)
                        g++;
                    if (g == group_count)
                        groups[group_count++] = group;
                }
                if (conflict) {
                    r->status = GPGPU_SIM_ERROR;
                    snprintf(r->error, sizeof r->error,
                             "PC 0x%x: lanes store different values to DDR byte 0x%08x in one instruction; "
                             "which one lands is unspecified",
                             pc_bytes, lowest_conflict);
                    return;
                }
                r->ddr_bursts += group_count;
            } else {
                uint32_t groups[MAX_LANES], first[MAX_LANES], last[MAX_LANES], group_count = 0;
                uint32_t values[MAX_LANES];
                for (uint32_t lane = 0; lane < lanes; lane++) {
                    values[lane] = *word_at(sim, targets[lane], addrs[lane]);
                    if (targets[lane] != TGT_DDR)
                        continue;
                    r->ddr_lane_loads++;
                    uint32_t group = addrs[lane] / c->group_bytes;
                    uint32_t beat = (addrs[lane] % c->group_bytes) >> c->beat_lsb, g = 0;
                    while (g < group_count && groups[g] != group)
                        g++;
                    if (g == group_count) {
                        groups[group_count] = group;
                        first[group_count] = last[group_count] = beat;
                        group_count++;
                    } else {
                        first[g] = beat < first[g] ? beat : first[g];
                        last[g] = beat > last[g] ? beat : last[g];
                    }
                }
                r->ddr_read_bursts += group_count;
                for (uint32_t g = 0; g < group_count; g++)
                    r->ddr_read_beats += last[g] - first[g] + 1u;
                for (uint32_t lane = 0; lane < lanes; lane++)
                    set_reg(sim, lane, in.rd, load_value(in.op, values[lane], addrs[lane]));
            }
            break;
        }
        default: { /* ALU, register or immediate operand */
            const int immediate = is_immediate(in.op);
            for (uint32_t lane = 0; lane < lanes; lane++) {
                uint32_t a = sim->regs[lane][in.rs1];
                uint32_t b = immediate ? (uint32_t)in.imm : sim->regs[lane][in.rs2];
                set_reg(sim, lane, in.rd, alu(in.op, a, b));
            }
            break;
        }
        }
        pc = next;
    }
}
