#include "../gpgpu_runtime.h"
#include "nbody-3d.h"

#include <stdint.h>

#define CORES GPGPU_NUM_CORES

/*
 * Host/kernel state layout starting at the pointer passed in GPGPU_ARGS[0].
 *
 * base + 0 * CORES -> pos_x[CORES]
 * base + 1 * CORES -> pos_y[CORES]
 * base + 2 * CORES -> pos_z[CORES]
 * base + 3 * CORES -> vel_x[CORES]
 * base + 4 * CORES -> vel_y[CORES]
 * base + 5 * CORES -> vel_z[CORES]
 */
#define POS_X_OFFSET (0u * CORES)
#define POS_Y_OFFSET (1u * CORES)
#define POS_Z_OFFSET (2u * CORES)
#define VEL_X_OFFSET (3u * CORES)
#define VEL_Y_OFFSET (4u * CORES)
#define VEL_Z_OFFSET (5u * CORES)
#define MASS_OFFSET (6u * CORES)

#define STATE_WORDS  (7u * CORES)

/*
 * One lane/body update.
 *
 * RISC-V:
 *   each SP calls this once for its own tid.
 *
 * x86:
 *   the native reference calls this for tid = 0..31 for each kernel call.
 *
 * This keeps the x86 and RISC-V logic as close as possible.
 */
static inline __attribute__((always_inline)) void nbody_3d_lane(
    unsigned int tid,
    volatile int *base,
    int steps,
    int reset
)
{
    volatile int *pos_x = base + POS_X_OFFSET;
    volatile int *pos_y = base + POS_Y_OFFSET;
    volatile int *pos_z = base + POS_Z_OFFSET;
    volatile int *vel_x = base + VEL_X_OFFSET;
    volatile int *vel_y = base + VEL_Y_OFFSET;
    volatile int *vel_z = base + VEL_Z_OFFSET;
    volatile int *mass = base + MASS_OFFSET;

    int reset_mask = -nonzero_int(reset);

    int old_px = pos_x[tid];
    int old_py = pos_y[tid];
    int old_pz = pos_z[tid];
    int old_vx = vel_x[tid];
    int old_vy = vel_y[tid];
    int old_vz = vel_z[tid];

    pos_x[tid] = select_int(old_px, init_x(tid), reset_mask);
    pos_y[tid] = select_int(old_py, init_y(tid), reset_mask);
    pos_z[tid] = select_int(old_pz, init_z(tid), reset_mask);
    vel_x[tid] = select_int(old_vx, init_vx(tid), reset_mask);
    vel_y[tid] = select_int(old_vy, init_vy(tid), reset_mask);
    vel_z[tid] = select_int(old_vz, init_vz(tid), reset_mask);

    for (int step = 0; step < steps; step++) {
        int xi = pos_x[tid];
        int yi = pos_y[tid];
        int zi = pos_z[tid];

        int ax = 0;
        int ay = 0;
        int az = 0;

        for (unsigned int j = 0; j < CORES; j++) {
            int xj = pos_x[j];
            int yj = pos_y[j];
            int zj = pos_z[j];

            int dx = xj - xi;
            int dy = yj - yi;
            int dz = zj - zi;

            int w = force_weight(dx, dy, dz) * mass[j];

            ax += sign_int(dx) * w;
            ay += sign_int(dy) * w;
            az += sign_int(dz) * w;
        }

        int ax_mask = ax >> 31;
        int ay_mask = ay >> 31;
        int az_mask = az >> 31;

        int vx = vel_x[tid] + ((ax + (ax_mask & 3)) >> 2);
        int vy = vel_y[tid] + ((ay + (ay_mask & 3)) >> 2);
        int vz = vel_z[tid] + ((az + (az_mask & 3)) >> 2);

        pos_x[tid] = xi + vx;
        pos_y[tid] = yi + vy;
        pos_z[tid] = zi + vz;
        vel_x[tid] = vx;
        vel_y[tid] = vy;
        vel_z[tid] = vz;
    }
}

#ifdef __riscv

void kernel_main(void)
{
    unsigned int tid = gpgpu_thread_id();

    /*
     * Host-written arguments:
     *   GPGPU_ARGS[0] = base pointer byte address
     *   GPGPU_ARGS[1] = steps per kernel call
     *   GPGPU_ARGS[2] = reset, usually 1 only for the first kernel call
     *   GPGPU_ARGS[3] = reserved
     */
    volatile int *base = (volatile int *)(uintptr_t)GPGPU_ARGS[0];

    int steps = GPGPU_ARGS[1];
    int reset = GPGPU_ARGS[2];

    nbody_3d_lane(tid, base, steps, reset);

    return;
}

GPGPU_START(kernel_main)

#else

#include <stdio.h>
#include <stdlib.h>

static int state[STATE_WORDS];

static void print_csv_header(void)
{
    printf("step");

    for (unsigned int body = 0; body < CORES; body++) {
        printf(",x%u,y%u,z%u", body, body, body);
    }

    printf("\n");
}

static void print_csv_row(int step, volatile int *base)
{
    volatile int *pos_x = base + POS_X_OFFSET;
    volatile int *pos_y = base + POS_Y_OFFSET;
    volatile int *pos_z = base + POS_Z_OFFSET;

    printf("%d", step);

    for (unsigned int body = 0; body < CORES; body++) {
        printf(",%d,%d,%d", pos_x[body], pos_y[body], pos_z[body]);
    }

    printf("\n");
}

int main(int argc, char **argv)
{
    int kernel_calls = 100;
    int steps_per_call = 1;

    /*
     * Optional native arguments:
     *
     *   ./nbody-3d_x86 [kernel_calls] [steps_per_call]
     *
     * Examples:
     *   ./nbody-3d_x86 1000 1 > data.csv
     *   ./nbody-3d_x86 100 10 > data.csv
     */
    if (argc >= 2) {
        kernel_calls = atoi(argv[1]);
    }

    if (argc >= 3) {
        steps_per_call = atoi(argv[2]);
    }

    if (kernel_calls < 1) {
        kernel_calls = 1;
    }

    if (steps_per_call < 1) {
        steps_per_call = 1;
    }

    volatile int *base = (volatile int *)state;

    print_csv_header();

    int current_step = 0;

    for (int call = 0; call < kernel_calls; call++) {
        int reset = (call == 0);

        /*
         * Same logical ABI as the FPGA version:
         * one kernel call executes steps_per_call simulation steps.
         *
         * The loop over tid emulates the 32 SPs on x86.
         */
        for (unsigned int tid = 0; tid < CORES; tid++) {
            nbody_3d_lane(tid, base, steps_per_call, reset);
        }

        current_step += steps_per_call;
        print_csv_row(current_step, base);
    }

    return 0;
}

#endif
