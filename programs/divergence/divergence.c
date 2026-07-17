#define CORES 32

#ifdef __riscv
#include "../gpgpu_runtime.h"

volatile int branch_out[CORES] = {0};
volatile int join_out[CORES] = {0};
volatile int test[CORES/4] = {0};

void main(void)
{
    unsigned int threadIdx_x = gpgpu_thread_id();

    if (threadIdx_x < 16u) {
        branch_out[threadIdx_x] = 111;
        if (threadIdx_x < 8u) {
            test[threadIdx_x] = 444;
        } else {
            test[threadIdx_x] = 555;
        }
    } else {
        branch_out[threadIdx_x] = 222;
    }

    join_out[threadIdx_x] = 333;
}

GPGPU_START(main)

#else
#include <stdio.h>

int branch_out[CORES] = {0};
int join_out[CORES] = {0};

int main(void)
{
    for (int threadIdx_x = 0; threadIdx_x < CORES; threadIdx_x++) {
        if (threadIdx_x < 16) {
            branch_out[threadIdx_x] = 111;
        } else {
            branch_out[threadIdx_x] = 222;
        }

        join_out[threadIdx_x] = 333;
    }

    printf("branch_out: ");
    for (int i = 0; i < CORES; i++) {
        printf("%d ", branch_out[i]);
    }

    printf("\njoin_out: ");
    for (int i = 0; i < CORES; i++) {
        printf("%d ", join_out[i]);
    }
    printf("\n");

    return 0;
}
#endif
