#include "gpgpu_runtime.h"

/* Volatile indirect calls exercise real nested ILP32 returns without asking
 * this RV32 subset to execute the AUIPC emitted by GCC's non-relaxed calls. */
static __attribute__((noinline)) unsigned leaf(unsigned value)
{
    return value + 100u;
}

static __attribute__((noinline)) unsigned middle(unsigned value)
{
    unsigned (*volatile call)(unsigned) = leaf;
    return call(value) + 5u;
}

static __attribute__((used, noinline)) void kernel_main(void)
{
    unsigned tid = gpgpu_thread_id();
    unsigned (*volatile call)(unsigned) = middle;
    volatile unsigned *output;
    __asm__ volatile("addi %0, x0, 0" : "=r"(output));
    output[tid] = call(tid);
}

GPGPU_START(kernel_main)
