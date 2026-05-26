#define NUM_PROCESSORS 32
#define NUM_BODIES NUM_PROCESSORS

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
    int x[NUM_BODIES];
    int y[NUM_BODIES];
    int vx[NUM_BODIES];
    int vy[NUM_BODIES];
    int mass[NUM_BODIES];
    int i, j, step;

    // Place all bodies around a rough circle centered on the screen.
    for (i = 0; i < NUM_BODIES; i++) {
        int ox = 0;
        int oy = 0;

        // Pick one of 16 integer circle offsets; avoids trig/lib calls.
        switch (i & 15) {
            case 0:  ox =  60; oy =   0; break;
            case 1:  ox =  55; oy =  23; break;
            case 2:  ox =  42; oy =  42; break;
            case 3:  ox =  23; oy =  55; break;
            case 4:  ox =   0; oy =  60; break;
            case 5:  ox = -23; oy =  55; break;
            case 6:  ox = -42; oy =  42; break;
            case 7:  ox = -55; oy =  23; break;
            case 8:  ox = -60; oy =   0; break;
            case 9:  ox = -55; oy = -23; break;
            case 10: ox = -42; oy = -42; break;
            case 11: ox = -23; oy = -55; break;
            case 12: ox =   0; oy = -60; break;
            case 13: ox =  23; oy = -55; break;
            case 14: ox =  42; oy = -42; break;
            default: ox =  55; oy = -23; break;
        }

        x[i] = (100 + ox) << POS_SHIFT;   // Initial x position in fixed point.
        y[i] = (100 + oy) << POS_SHIFT;   // Initial y position in fixed point.
        vx[i] = -oy >> 3;                 // Tangential x velocity for orbit-like motion.
        vy[i] =  ox >> 3;                 // Tangential y velocity for orbit-like motion.
        mass[i] = 1;                      // Give every body mass so all processors do useful work.
    }

    mass[0] = 3;                          // Keep body 0 heavier as the center-ish anchor.

    #ifdef __riscv
    int threadIdx_x;
    __asm__ volatile("mv %0, x31" : "=r"(threadIdx_x)); // Read GPU processor index.
    i = threadIdx_x;                      // This processor owns body i.
    #else
    printf("step");                     // Start CSV header with step number.
    for (i = 0; i < NUM_BODIES; i++) {
        printf(",x%d,y%d", i, i);        // Add one x/y column pair per body.
    }
    printf("\n");
    #endif

    for (step = 0; step < STEPS; step++) {
        #ifdef __riscv
        int ax = 0;
        int ay = 0;

        for (j = 0; j < NUM_BODIES; j++) {
            int dx = x[j] - x[i];
            int dy = y[j] - y[i];
            int sx = sign_int(dx);
            int sy = sign_int(dy);
            int px = pull_strength(dx);
            int py = pull_strength(dy);

            ax += sx * px * mass[j];
            ay += sy * py * mass[j];
        }

        vx[i] += ax;
        vy[i] += ay;

        vx[i] -= vx[i] >> DAMP_SHIFT;
        vy[i] -= vy[i] >> DAMP_SHIFT;

        x[i] += vx[i];
        y[i] += vy[i];
        #else
        int ax[NUM_BODIES] = {0, 0, 0};
        int ay[NUM_BODIES] = {0, 0, 0};

        for (i = 0; i < NUM_BODIES; i++) {
            for (j = 0; j < NUM_BODIES; j++) {
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

        for (i = 0; i < NUM_BODIES; i++) {
            vx[i] += ax[i];
            vy[i] += ay[i];

            vx[i] -= vx[i] >> DAMP_SHIFT;
            vy[i] -= vy[i] >> DAMP_SHIFT;

            x[i] += vx[i];
            y[i] += vy[i];
        }

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
        gpu_output[i << 1] = pixel_pos(x[i]);
        gpu_output[(i << 1) + 1] = pixel_pos(y[i]);
    }
    #endif

    return 0;
}
