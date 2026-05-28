#define NUM_PROCESSORS 32
#define NUM_BODIES NUM_PROCESSORS

#ifndef NBODY_STEPS
#define NBODY_STEPS 360
#endif
#define STEPS NBODY_STEPS
#define POS_SHIFT 4
#define BLACK_HOLE_BODY 0
#define BLACK_HOLE_X 100
#define BLACK_HOLE_Y 100
#define BLACK_HOLE_MASS 64
#define STAR_MASS 1
#define MIN_ORBIT_RADIUS 40
#define ORBIT_RADIUS_SPREAD 128
#define ORBIT_PHASE_STEPS 32
#define ORBIT_PHASE_SHIFT 6
#define ORBIT_PHASE_MASK (ORBIT_PHASE_STEPS - 1)
#define ORBIT_PHASE_FP_MASK ((ORBIT_PHASE_STEPS << ORBIT_PHASE_SHIFT) - 1)
#define GPU_OUTPUT_BASE 0x1000

static inline __attribute__((always_inline)) int pixel_pos(int value) {
    return value >> POS_SHIFT;
}

static inline __attribute__((always_inline)) unsigned int next_random(unsigned int *seed) {
    *seed = (*seed * 1103515245u) + 12345u;
    return *seed;
}

static inline __attribute__((always_inline)) void orbit_direction(int slot, int *dx, int *dy) {
    // 32 fixed-point direction vectors scaled by 64; avoids trig/lib calls.
    switch (slot & ORBIT_PHASE_MASK) {
        case 0:  *dx =  64; *dy =   0; break;
        case 1:  *dx =  63; *dy =  12; break;
        case 2:  *dx =  59; *dy =  24; break;
        case 3:  *dx =  53; *dy =  36; break;
        case 4:  *dx =  45; *dy =  45; break;
        case 5:  *dx =  36; *dy =  53; break;
        case 6:  *dx =  24; *dy =  59; break;
        case 7:  *dx =  12; *dy =  63; break;
        case 8:  *dx =   0; *dy =  64; break;
        case 9:  *dx = -12; *dy =  63; break;
        case 10: *dx = -24; *dy =  59; break;
        case 11: *dx = -36; *dy =  53; break;
        case 12: *dx = -45; *dy =  45; break;
        case 13: *dx = -53; *dy =  36; break;
        case 14: *dx = -59; *dy =  24; break;
        case 15: *dx = -63; *dy =  12; break;
        case 16: *dx = -64; *dy =   0; break;
        case 17: *dx = -63; *dy = -12; break;
        case 18: *dx = -59; *dy = -24; break;
        case 19: *dx = -53; *dy = -36; break;
        case 20: *dx = -45; *dy = -45; break;
        case 21: *dx = -36; *dy = -53; break;
        case 22: *dx = -24; *dy = -59; break;
        case 23: *dx = -12; *dy = -63; break;
        case 24: *dx =   0; *dy = -64; break;
        case 25: *dx =  12; *dy = -63; break;
        case 26: *dx =  24; *dy = -59; break;
        case 27: *dx =  36; *dy = -53; break;
        case 28: *dx =  45; *dy = -45; break;
        case 29: *dx =  53; *dy = -36; break;
        case 30: *dx =  59; *dy = -24; break;
        default: *dx =  63; *dy = -12; break;
    }
}

static inline __attribute__((always_inline)) void set_orbit_position(
    int body,
    int *x,
    int *y,
    int *vx,
    int *vy,
    int radius_x,
    int radius_y,
    int phase
) {
    int dir_x = 0;
    int dir_y = 0;
    int ox;
    int oy;
    int old_x = x[body];
    int old_y = y[body];

    {
        int next_x = 0;
        int next_y = 0;
        int frac = phase & ((1 << ORBIT_PHASE_SHIFT) - 1);
        int whole_phase = phase >> ORBIT_PHASE_SHIFT;

        orbit_direction(whole_phase, &dir_x, &dir_y);
        orbit_direction(whole_phase + 1, &next_x, &next_y);

        // Interpolate between direction-table entries so bodies move smoothly
        // every frame. Without this, a large ORBIT_PHASE_SHIFT slows motion by
        // holding each body still for many frames and then jumping to the next
        // table position.
        dir_x = ((dir_x * ((1 << ORBIT_PHASE_SHIFT) - frac)) + (next_x * frac)) >> ORBIT_PHASE_SHIFT;
        dir_y = ((dir_y * ((1 << ORBIT_PHASE_SHIFT) - frac)) + (next_y * frac)) >> ORBIT_PHASE_SHIFT;
    }

    ox = (dir_x * radius_x) >> 6;
    oy = (dir_y * radius_y) >> 6;

    x[body] = (BLACK_HOLE_X + ox) << POS_SHIFT;
    y[body] = (BLACK_HOLE_Y + oy) << POS_SHIFT;
    vx[body] = x[body] - old_x;
    vy[body] = y[body] - old_y;
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
    int radius_x[NUM_BODIES];
    int radius_y[NUM_BODIES];
    int phase[NUM_BODIES];
    int orbit_speed[NUM_BODIES];
    int i, step;
    int star_mass = STAR_MASS;
    unsigned int seed = 0x338u;

    // Body 0 is the black hole: heavy and fixed at the galaxy center.
    x[BLACK_HOLE_BODY] = BLACK_HOLE_X << POS_SHIFT;
    y[BLACK_HOLE_BODY] = BLACK_HOLE_Y << POS_SHIFT;
    vx[BLACK_HOLE_BODY] = 0;
    vy[BLACK_HOLE_BODY] = 0;
    radius_x[BLACK_HOLE_BODY] = 0;
    radius_y[BLACK_HOLE_BODY] = 0;
    phase[BLACK_HOLE_BODY] = 0;
    orbit_speed[BLACK_HOLE_BODY] = 0;

    // Spread the remaining bodies throughout a flattened disk around the black
    // hole instead of placing them all on one circle. The initial velocity is
    // perpendicular/tangential because each body advances around its own orbit.
    // ORBIT_RADIUS_SPREAD is a power of two so the radius uses a bit-mask instead
    // of %, because unsigned remainder may compile to unsupported remu.
    for (i = 1; i < NUM_BODIES; i++) {
        int disk_flatten;
        radius_x[i] = MIN_ORBIT_RADIUS + (int)((next_random(&seed) >> 24) & (ORBIT_RADIUS_SPREAD - 1));
        disk_flatten = 30 + (int)((next_random(&seed) >> 26) & 15);
        radius_y[i] = (radius_x[i] * disk_flatten) >> 6;
        phase[i] = ((int)(next_random(&seed) >> 27) & ORBIT_PHASE_MASK) << ORBIT_PHASE_SHIFT;

        // The phase is fixed-point: ORBIT_PHASE_SHIFT fractional bits means
        // orbit_speed=4 still takes about 512 frames for one full orbit, but
        // combined with interpolation it updates visible positions nearly every
        // frame instead of appearing frozen/laggy.
        orbit_speed[i] = 4;

        set_orbit_position(i, x, y, vx, vy, radius_x[i], radius_y[i], phase[i]);
        vx[i] = (-((y[i] >> POS_SHIFT) - BLACK_HOLE_Y) * orbit_speed[i] * star_mass) >> 2;
        vy[i] = ( ((x[i] >> POS_SHIFT) - BLACK_HOLE_X) * orbit_speed[i] * star_mass) >> 2;
    }

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
        if (i == BLACK_HOLE_BODY) {
            x[i] = BLACK_HOLE_X << POS_SHIFT;
            y[i] = BLACK_HOLE_Y << POS_SHIFT;
            vx[i] = 0;
            vy[i] = 0;
        } else {
            phase[i] = (phase[i] + orbit_speed[i]) & ORBIT_PHASE_FP_MASK;
            set_orbit_position(i, x, y, vx, vy, radius_x[i], radius_y[i], phase[i]);
        }
        #else
        for (i = 0; i < NUM_BODIES; i++) {
            if (i == BLACK_HOLE_BODY) {
                x[i] = BLACK_HOLE_X << POS_SHIFT;
                y[i] = BLACK_HOLE_Y << POS_SHIFT;
                vx[i] = 0;
                vy[i] = 0;
                continue;
            }

            phase[i] = (phase[i] + orbit_speed[i]) & ORBIT_PHASE_FP_MASK;
            set_orbit_position(i, x, y, vx, vy, radius_x[i], radius_y[i], phase[i]);
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
