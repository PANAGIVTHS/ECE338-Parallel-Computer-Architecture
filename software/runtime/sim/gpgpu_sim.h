#ifndef GPGPU_SIM_H
#define GPGPU_SIM_H

/*
 * Functional simulator of the GPGPU: one SM, all lanes in lockstep, with the
 * rules of the Python model (tools/tests/gpgpu_model.py), which is its
 * reference (docs/runtime-spec.md, section 10):
 *
 * - Branches, JALR and ECALL follow lane 0. A branch the lanes disagree on is
 *   reported, and execution goes on as the hardware does.
 * - Registers start as gpu_pkg::reg_reset_value: x2 = STACK_P_INIT, x31 the
 *   lane index (read only), the rest 0. The PC wraps at IMEM_ENTRIES.
 * - Accesses decode as MemorySubsystemPkg::decode_access; a memory
 *   instruction with a lane whose status is not OK faults and stops the run.
 * - Stores of one instruction to the same shared-memory byte take effect in
 *   ascending lane order. Lanes storing different values to one DDR byte in
 *   one instruction is an error: which one lands is unspecified.
 *
 * DDR is a window of host memory supplied by the caller, from ddr_low to
 * ddr_high: the runtime maps it at the board's addresses.
 */

#include <stddef.h>
#include <stdint.h>

typedef struct {
    uint32_t lanes;
    uint32_t imem_words;
    uint32_t smem_words;
    uint32_t smem_base;
    uint32_t fb0_base, fb1_base, fb_size;
    uint32_t gmem_base, gmem_size;
    uint32_t stack_p_init;
    uint32_t txd_register;
    uint32_t group_bytes;
    uint32_t beat_lsb;
    int ddr_enable;
    uint32_t st_ok, st_unmapped, st_permission, st_misaligned;
} gpgpu_sim_config_t;

/* The configuration of the RTL this build was generated for (gpgpu_hw.h). */
gpgpu_sim_config_t gpgpu_sim_default_config(void);

/* Lowest and highest address (exclusive) of the DDR regions of a configuration. */
void gpgpu_sim_ddr_bounds(const gpgpu_sim_config_t *config, uint32_t *low, uint32_t *high);

typedef enum {
    GPGPU_SIM_DONE,  /* ECALL service 0 */
    GPGPU_SIM_FAULT, /* a memory access failed; see fault_* */
    GPGPU_SIM_ERROR, /* the program cannot be simulated; see error */
    GPGPU_SIM_LIMIT  /* the instruction limit, or the caller's stop request */
} gpgpu_sim_status_t;

typedef struct {
    gpgpu_sim_status_t status;
    uint32_t fault_pc;    /* byte address of the faulting instruction */
    uint32_t fault_lanes; /* bit i: lane i got a status that is not OK */
    uint32_t fault_kinds; /* bit k-1: some lane got status k */
    char error[192];
    uint64_t instructions; /* warp instructions executed, the ECALL included */
    uint64_t ddr_bursts;   /* AXI write bursts */
    uint64_t ddr_lane_stores;
    uint64_t ddr_lane_loads;
    uint64_t ddr_read_bursts;
    uint64_t ddr_read_beats;
    uint64_t smem_lane_accesses;
} gpgpu_sim_result_t;

typedef struct gpgpu_sim gpgpu_sim_t;

/* `ddr` is host memory for the bytes [ddr_low, ddr_high) of the device. With
 * `touched`, one bit per DDR word is set on every store (the RTL cases list
 * the words written). Returns NULL when out of memory. */
gpgpu_sim_t *gpgpu_sim_create(const gpgpu_sim_config_t *config, uint8_t *ddr, uint32_t ddr_low, uint32_t ddr_high,
                              uint8_t *touched);
void gpgpu_sim_destroy(gpgpu_sim_t *sim);

const gpgpu_sim_config_t *gpgpu_sim_config(const gpgpu_sim_t *sim);
uint32_t *gpgpu_sim_imem(gpgpu_sim_t *sim); /* imem_words words */
uint32_t *gpgpu_sim_smem(gpgpu_sim_t *sim); /* smem_words words */

/* Called once for every branch or ECALL the lanes disagree on. */
typedef void (*gpgpu_sim_divergence_fn)(void *context, uint32_t pc);
/* Polled now and then during a run: nonzero stops it with GPGPU_SIM_LIMIT. */
typedef int (*gpgpu_sim_stop_fn)(void *context);

/* Reset the registers and the PC, then run until completion, a fault, an
 * error, max_instructions or a stop request. */
void gpgpu_sim_run(gpgpu_sim_t *sim, uint64_t max_instructions, gpgpu_sim_divergence_fn divergence,
                   gpgpu_sim_stop_fn stop, void *context, gpgpu_sim_result_t *result);

/* A lane's register after a run. */
uint32_t gpgpu_sim_register(const gpgpu_sim_t *sim, uint32_t lane, uint32_t index);

#endif /* GPGPU_SIM_H */
