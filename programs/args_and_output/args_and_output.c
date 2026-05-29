#define CORES 32

#ifdef __riscv

#include "../gpgpu_runtime.h"

__attribute__((noinline, used, patchable_function_entry(1, 0)))
void kernel_main(void)
{
    unsigned int tid = gpgpu_thread_id();

    int a0 = GPGPU_ARGS[0];
    int a1 = GPGPU_ARGS[1];
    int a2 = GPGPU_ARGS[2];
    int a3 = GPGPU_ARGS[3];

    GPGPU_OUTPUT[(tid << 1) + 0] = a0 + (int)tid;
    GPGPU_OUTPUT[(tid << 1) + 1] = a1 + a2 + a3 + (int)tid;

    return;
}

GPGPU_START(kernel_main)

#else

#include <stdio.h>

int main(void)
{
    int a0 = 10;
    int a1 = 20;
    int a2 = 30;
    int a3 = 40;

    printf("tid,out0,out1\n");

    for (unsigned int tid = 0; tid < CORES; tid++) {
        int out0 = a0 + (int)tid;
        int out1 = a1 + a2 + a3 + (int)tid;

        printf("%u,%d,%d\n", tid, out0, out1);
    }

    return 0;
}

#endif