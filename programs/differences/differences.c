#include "../gpgpu_runtime.h"
#define CORES GPGPU_NUM_CORES

#ifdef __riscv

int data[CORES + 1] = {0};
int diff[CORES] = {0};

void kernel_main(void)
{
    unsigned int tid = gpgpu_thread_id();

    // Initialize array
    data[tid+1] = tid;

    // Calculate differences
    diff[tid] = data[tid] - data[tid + 1];

    // Write back the results
    GPGPU_OUTPUT[tid] = diff[tid];

    return;
}

GPGPU_START(kernel_main)

#else

#include <stdio.h>

int data[CORES + 1] = {0};
int diff[CORES] = {0};

int main(void)
{
    /*
     * Padding:
     * data[0] is the artificial left neighbor of body/index 0.
     */
    data[0] = 0;

    /*
     * Logical parallel initialization:
     * data[tid + 1] = tid
     */
    for (int tid = 0; tid < CORES; tid++) {
        data[tid + 1] = tid;
    }

    /*
     * Adjacent difference without special case:
     * diff[tid] = data[tid + 1] - data[tid]
     */
    for (int tid = 0; tid < CORES; tid++) {
        diff[tid] = data[tid + 1] - data[tid];
    }

    printf("Index | data[i+1] | data[i] | diff[i]\n");
    printf("--------------------------------------\n");

    for (int i = 0; i < CORES; i++) {
        printf("%5d | %9d | %7d | %7d\n",
               i,
               data[i + 1],
               data[i],
               diff[i]);
    }

    return 0;
}

#endif
