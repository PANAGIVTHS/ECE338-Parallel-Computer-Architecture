/*
 * memspaces: one kernel that touches every memory space of linker.ld.
 *
 *   GPGPU_ARGS  DMEM   op                 host-written argument, DMEM byte 0
 *   .shared     DMEM   out[]              GPGPU_SHARED: the results, zero at load
 *   stack       DMEM   tmp[]              per-lane private array
 *   .rodata     GMEM   gain[]             const table, read with a per-lane index
 *   .rodata     GMEM   (jump table)       switch (op), 6 dense cases; op is uniform
 *   .data       GMEM   call_count, bias[] initialized globals
 *   .bss        GMEM   last_op, slots[]   zero-initialized globals
 *
 * It shows the code each space produces and tests that the host loads
 * .rodata/.data into GMEM and zeroes .bss and .shared, once per program load:
 * the globals keep their values from one launch to the next.
 *
 * Jump tables are off for every kernel (-fno-jump-tables): this one asks for
 * them with optimize("jump-tables"), so the switch loads its target from
 * GMEM. op is the same in every lane, so every lane jumps to the same case.
 *
 * Args:
 *   GPGPU_ARGS[0] = op, 0..5 selects a case of the switch, any other value: default
 *
 * Output, launch k (k = 0 for the first launch after the program loads):
 *   out[tid] = op_result(op, tid) + gain[tid & 7] + bias[tid & 3]
 *              + (100 + k) + (k ? tid + 1 : 0) + (4 * tid + 6)
 * then slots[tid] = tid + 1, last_op = op and call_count = 101 + k.
 */
#include "../gpgpu_runtime.h"

#define CORES GPGPU_NUM_CORES

/* .rodata: read-only, shared by all lanes. */
static const int gain[8] = {3, 1, 4, 1, 5, 9, 2, 6};

/* .data: initialized, writable, shared by all lanes. */
int call_count = 100;
int bias[4] = {1000, 2000, 3000, 4000};

/* .bss: zero at program load, writable, shared by all lanes. */
int last_op;
int slots[CORES];

/* A dense switch: with jump tables on, GCC emits a table of 6 code addresses. */
static inline __attribute__((always_inline)) int op_result(int op, int tid)
{
    switch (op) {
    case 0:  return tid;
    case 1:  return tid * 3;
    case 2:  return tid + 77;
    case 3:  return -tid;
    case 4:  return tid << 4;
    case 5:  return tid ^ 0x55;
    default: return 0;
    }
}

#ifdef __riscv

/* .shared: DMEM, shared by all lanes, zero at program load. */
GPGPU_SHARED int out[CORES];

__attribute__((noinline, optimize("jump-tables"))) void kernel_main(void)
{
    unsigned int tid = gpgpu_thread_id();
    int op = GPGPU_ARGS[0];

    /* Stack: volatile keeps the array in this lane's stack slice. */
    volatile int tmp[4];
    for (int i = 0; i < 4; i++)
        tmp[i] = (int)tid + i;
    int tmp_sum = tmp[0] + tmp[1] + tmp[2] + tmp[3];

    out[tid] = op_result(op, (int)tid) + gain[tid & 7] + bias[tid & 3] + call_count + slots[tid] + tmp_sum;

    /* Per-lane slot: every lane writes a different word, no race. */
    slots[tid] = (int)tid + 1;

    /* Shared scalars, meant for lane 0 only. This is a per-lane branch (bne on
     * tid): until divergence is implemented every lane follows lane 0 and all
     * of them store the same values, which happens to give the same result. */
    if (tid == 0) {
        last_op = op;
        call_count = call_count + 1;
    }
}

GPGPU_START(kernel_main)

#else
#include <stdio.h>
#include <stdlib.h>

/* The expected out[] of launch `launch` (0 = first after the program loads). */
int main(int argc, char **argv)
{
    int launches = argc > 1 ? atoi(argv[1]) : 2;

    for (int launch = 0; launch < launches; launch++) {
        for (int op = 0; op <= 6; op++) {
            printf("launch %d op %d:", launch, op);
            for (int tid = 0; tid < CORES; tid++) {
                int slot = launch ? tid + 1 : 0;
                printf(" %d", op_result(op, tid) + gain[tid & 7] + bias[tid & 3] + 100 + launch + slot + 4 * tid + 6);
            }
            printf("\n");
        }
    }
    return 0;
}
#endif
