#define SIZE 10
#define NUM_SPS 2

int data[SIZE] = {2, 5, 9, 15, 23, 33, 45, 59, 75, 93};
int diff[SIZE];

#ifdef __riscv
int _start() {
    int threadIdx_x;

    // Read the custom hardware register x31 into the variable threadIdx_x
    __asm__ volatile("mv %0, x31" : "=r"(threadIdx_x));

    for (int i = threadIdx_x; i < SIZE; i += NUM_SPS) {
        if (i == 0) {
            diff[0] = data[0];
        } else {
            diff[i] = data[i] - data[i - 1];
        }
    }

    return 0;
}
#else
#include <stdio.h>
int main() {
    for (int threadIdx_x = 0; threadIdx_x < SIZE; threadIdx_x++) {
        if (threadIdx_x < SIZE) {
            if (threadIdx_x == 0) {
                diff[0] = data[0];
            } else {
                diff[threadIdx_x] = data[threadIdx_x] - data[threadIdx_x - 1];
            }
        }
    }

    printf("Index | Data | Adjacent Difference\n");
    printf("----------------------------------\n");
    for (int i = 0; i < SIZE; i++) {
        printf("  %2d  |  %2d  |  %2d\n", i, data[i], diff[i]);
    }

    return 0;
}
#endif
