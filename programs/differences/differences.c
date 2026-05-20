#define CORES 32

#ifdef __riscv
int data[CORES] = {1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32};
int diff[CORES] = {0};

__attribute__((naked)) int _start() {
    int threadIdx_x;
    __asm__ volatile("mv %0, x31" : "=r"(threadIdx_x));

    for (int i = threadIdx_x; i < CORES; i += CORES) {
        if (i == 0) {
            diff[0] = data[0];
        } else {
            diff[i] = data[i] - data[i - 1];
        }
    }

    asm volatile("jalr x0, 0(x1)");
    __builtin_unreachable();
}
#else
#include <stdio.h>
int data[CORES] = {1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32};
int diff[CORES] = {0};

int main()
{
    for (int threadIdx_x = 0; threadIdx_x < CORES; threadIdx_x++) {
        if (threadIdx_x == 0) {
            diff[0] = data[0];
        } else {
            diff[threadIdx_x] = data[threadIdx_x] - data[threadIdx_x - 1];
        }
    }

    printf("Index | Data | Adjacent Difference\n");
    printf("----------------------------------\n");

    for (int i = 0; i < CORES; i++) {
        printf("%5d | %4d | %4d\n", i, data[i], diff[i]);
    }

    return 0;
}

#endif
