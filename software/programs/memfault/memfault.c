#include "../gpgpu_runtime.h"

#define CORES GPGPU_NUM_CORES

#ifdef __riscv


void main(void)
{
    unsigned int tid = gpgpu_thread_id();

    volatile int *base = (volatile int *)(uintptr_t)GPGPU_ARGS[0];

    volatile int *indexes_array = base;
    volatile int *ten_array = base + (CORES + 1) + 0xFFFFF;

    // All SPs must write their thread id
    indexes_array[tid] = tid;

    // Αll SPs must access x and write it to their index
    int x = 10;
    ten_array[tid] = x;

    return;
}

GPGPU_START(main)

#else
#include <stdio.h>
int indexes_array[CORES] = {0};
int ten_array[CORES] = {0};

int main() {
    for (int i = 0; i < CORES; i++) {
        indexes_array[i] = i;
        ten_array[i] = 10;
    }

    printf("Indexes array: ");
    for (int i = 0; i < CORES; i++) {
        printf("%d ", indexes_array[i]);
    }

    printf("\nTen array: ");
    for (int i = 0; i < CORES; i++) {
        printf("%d ", ten_array[i]);
    }
    printf("\n");
}
#endif
