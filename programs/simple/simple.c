#ifdef __riscv
int _start() {
    int threadIdx_x;
    __asm__ volatile("mv %0, x31" : "=r"(threadIdx_x));

    // Test that thread index is written in correct position
    int indexes_array[2] = {0};
    indexes_array[threadIdx_x] = threadIdx_x;

    // Test that both SPs have accessed x and written it to the correct position
    int x = 10;
    int ten_array[2] = {0};
    ten_array[threadIdx_x] = x;
}
#else
#include <stdio.h>
int main() {
    printf("Expected:\n");
    printf("indexes_array: %d %d\n", 0, 1);
    printf("ten_array: %d %d\n", 10, 10);
}
#endif
