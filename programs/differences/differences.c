#define SIZE 10

#ifdef __riscv
int _start() {
#else
#include <stdio.h>
int main() {
#endif
    int data[SIZE] = {2, 5, 9, 15, 23, 33, 45, 59, 75, 93};
    int diff[SIZE];
    
    int i;
    diff[0] = data[0];

    #ifdef __riscv
    for (i = 1; i < SIZE; i++) {
        diff[i] = data[i] - data[i-1];
    }
    #else
    for (i = 1; i < SIZE; i++) {
        diff[i] = data[i] - data[i-1];
    }
    #endif

    #ifdef __riscv
    #else
    printf("Index | Data | Adjacent Difference\n");
    printf("----------------------------------\n");
    for (i = 0; i < SIZE; i++) {
        printf("  %2d  |  %2d  |  %2d\n", i, data[i], diff[i]);
    }
    #endif

    return 0;
}
