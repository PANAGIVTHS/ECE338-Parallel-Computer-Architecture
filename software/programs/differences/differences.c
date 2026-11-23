#include "../gpgpu_runtime.h"
#define CORES GPGPU_NUM_CORES

#ifdef __riscv

/* Shared memory (DMEM): the host writes data[0..CORES] and reads diff[] back
 * through the symbol (differences/fpga.py). data[0] is padding. */
GPGPU_SHARED volatile int differences_buffer[2 * CORES + 1];

void main(void)
{
    unsigned int tid = gpgpu_thread_id();

    volatile int *data = differences_buffer;
    volatile int *diff = differences_buffer + (CORES + 1);

    // Calculate differences
    diff[tid] = data[tid + 1] - data[tid];

    return;
}

GPGPU_START(main)

#else

#include <stdio.h>

int main(void)
{
    int data[CORES + 1] = {0};
    int diff[CORES] = {0};

    /*
     * Same layout as the FPGA adapter:
     *
     * data[0] is padding.
     * data[1..32] are logical input values.
     */
    data[0] = 0;

    for (int i = 0; i < CORES; i++) {
        data[i + 1] = i;
    }

    for (int tid = 0; tid < CORES; tid++) {
        diff[tid] = data[tid + 1] - data[tid];
    }

    printf("call,index,data_left,data_right,diff,expected,ok\n");

    for (int i = 0; i < CORES; i++) {
        int data_left = data[i];
        int data_right = data[i + 1];
        int expected = data_right - data_left;
        int ok = diff[i] == expected;

        printf("%d,%d,%d,%d,%d,%d,%d\n",
               0,
               i,
               data_left,
               data_right,
               diff[i],
               expected,
               ok);
    }

    return 0;
}

#endif
