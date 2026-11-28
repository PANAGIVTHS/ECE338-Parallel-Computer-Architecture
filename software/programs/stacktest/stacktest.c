/*
 * stacktest: every lane reports its stack pointer and keeps a value on its
 * own stack, so the host can check that the lanes' stacks are apart
 * (docs/runtime-spec.md, section 3.3: GPGPU_STACK_STRIDE bytes per lane, at
 * the top of shared memory). The host passes the two arrays, stack_pointers
 * and stack_values, as parameters.
 */
#include "gpgpu_device.h"

GPGPU_DEVICE unsigned int stack_pointers[GPGPU_NUM_CORES];
GPGPU_DEVICE unsigned int stack_values[GPGPU_NUM_CORES];

GPGPU_GLOBAL void stacktest(unsigned int *pointers, unsigned int *values, unsigned int seed)
{
    unsigned int tid = gpgpu_thread_idx();
    unsigned int sp;

    /* volatile: the value goes through this lane's stack, not a register. */
    volatile unsigned int local = seed + tid;
    __asm__ volatile("mv %0, sp" : "=r"(sp));

    pointers[tid] = sp;
    values[tid] = local;
}
