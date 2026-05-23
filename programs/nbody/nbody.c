#define NUM_BODIES 3
#ifndef NBODY_STEPS
#define NBODY_STEPS 360
#endif
#define STEPS NBODY_STEPS
#define POS_SHIFT 4
#define DAMP_SHIFT 5
#define NEAR_LIMIT (32 << POS_SHIFT)
#define MID_LIMIT  (96 << POS_SHIFT)
#define FAR_LIMIT  (160 << POS_SHIFT)
#define GPU_OUTPUT_BASE 0x1000

static inline __attribute__((always_inline)) int abs_int(int value) {
    if (value < 0)
        return -value;
    return value;
}

static inline __attribute__((always_inline)) int sign_int(int value) {
    if (value > 0)
        return 1;
    if (value < 0)
        return -1;
    return 0;
}

static inline __attribute__((always_inline)) int pull_strength(int distance) {
    int ad = abs_int(distance);

    if (ad < NEAR_LIMIT)
        return 0;
    if (ad < MID_LIMIT)
        return 1;
    if (ad < FAR_LIMIT)
        return 2;
    return 3;
}

static inline __attribute__((always_inline)) int pixel_pos(int value) {
    return value >> POS_SHIFT;
}

#ifdef __riscv
int _start() {
#else
#include <stdio.h>
int main() {
#endif
    int x[NUM_BODIES]    = {100 << POS_SHIFT, 150 << POS_SHIFT,  50 << POS_SHIFT};
    int y[NUM_BODIES]    = {100 << POS_SHIFT, 150 << POS_SHIFT,  50 << POS_SHIFT};
    int vx[NUM_BODIES]   = {  0,              -10,               10};
    int vy[NUM_BODIES]   = {  0,                6,               -6};
    int mass[NUM_BODIES] = {  3,                1,                1};
    int i, j, step;

    #ifndef __riscv
    printf("step,x0,y0,x1,y1,x2,y2\n");
    #endif

    for (step = 0; step < STEPS; step++) {
        int ax[NUM_BODIES] = {0, 0, 0};
        int ay[NUM_BODIES] = {0, 0, 0};

        for (i = 0; i < NUM_BODIES; i++) {
            for (j = 0; j < NUM_BODIES; j++) {
                if (i != j) {
                    int dx = x[j] - x[i];
                    int dy = y[j] - y[i];
                    int sx = sign_int(dx);
                    int sy = sign_int(dy);
                    int px = pull_strength(dx);
                    int py = pull_strength(dy);

                    ax[i] += sx * px * mass[j];
                    ay[i] += sy * py * mass[j];
                }
            }
        }

        for (i = 0; i < NUM_BODIES; i++) {
            vx[i] += ax[i];
            vy[i] += ay[i];

            vx[i] -= vx[i] >> DAMP_SHIFT;
            vy[i] -= vy[i] >> DAMP_SHIFT;

            x[i] += vx[i];
            y[i] += vy[i];
        }

        #ifndef __riscv
        printf("%d", step);
        for (i = 0; i < NUM_BODIES; i++) {
            printf(",%d,%d", pixel_pos(x[i]), pixel_pos(y[i]));
        }
        printf("\n");
        #endif
    }

    #ifdef __riscv
    {
        volatile int *gpu_output = (volatile int *)GPU_OUTPUT_BASE;
        for (i = 0; i < NUM_BODIES; i++) {
            gpu_output[i << 1] = pixel_pos(x[i]);
            gpu_output[(i << 1) + 1] = pixel_pos(y[i]);
        }
    }
    #endif

    return 0;
}
