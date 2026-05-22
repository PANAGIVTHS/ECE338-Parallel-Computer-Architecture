#define CORES 32

#ifdef __riscv
int indexes_array[CORES] = {0};
int ten_array[CORES] = {0};

int main() {
    int threadIdx_x;
    __asm__ volatile("mv %0, x31" : "=r"(threadIdx_x));

    indexes_array[threadIdx_x] = threadIdx_x;

    // Test that all SPs have accessed x and written it to the correct position
    int x = 10;
    ten_array[threadIdx_x] = x;

    return 0;
}
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
