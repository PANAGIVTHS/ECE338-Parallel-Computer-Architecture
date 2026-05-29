#define CORES 32

#ifdef __riscv

#include "../gpgpu_runtime.h"

__attribute__((noinline, used, patchable_function_entry(1, 0))) // patchable adds nop
void main(void)
{
    unsigned int tid = gpgpu_thread_id();

    volatile int local = 0;

    unsigned int sp_value;
    __asm__ volatile("mv %0, x2" : "=r"(sp_value));

    local = sp_value;

    return;
}

GPGPU_START(main)

#else

#include <stdio.h>

int main(void)
{
    return 0;
}

#endif
