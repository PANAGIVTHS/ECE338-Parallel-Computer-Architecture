#include "../gpgpu_runtime.h"

#define CORES GPGPU_NUM_CORES
#define NBODY_MAGIC 0x4E424459u  /* "NBDY" */

#ifdef __riscv

volatile int pos_x[CORES];
volatile int pos_y[CORES];
volatile int vel_x[CORES];
volatile int vel_y[CORES];

static inline __attribute__((always_inline)) int nonzero_int(int x)
{
    unsigned int ux = (unsigned int)x;
    return (int)((ux | (0u - ux)) >> 31);
}

static inline __attribute__((always_inline)) int iabs_int(int x)
{
    int mask = x >> 31;
    return (x ^ mask) - mask;
}

static inline __attribute__((always_inline)) int sign_int(int x)
{
    int neg = (int)((unsigned int)x >> 31);
    int nz = nonzero_int(x);

    /*
     * x > 0  ->  1
     * x = 0  ->  0
     * x < 0  -> -1
     */
    return nz - (neg << 1);
}

static inline __attribute__((always_inline)) int select_int(int old_value, int new_value, int mask)
{
    return (old_value & ~mask) | (new_value & mask);
}

static inline __attribute__((always_inline)) int init_x(unsigned int i)
{
    return ((int)i * 13) - 208;
}

static inline __attribute__((always_inline)) int init_y(unsigned int i)
{
    return (((int)i * 29) & 255) - 128;
}

static inline __attribute__((always_inline)) int init_vx(unsigned int i)
{
    /*
     * Old version:
     *     return (i & 1u) ? 1 : -1;
     *
     * Branchless:
     *     bit 0 = 0 -> -1
     *     bit 0 = 1 ->  1
     */
    return (int)((i & 1u) << 1) - 1;
}

static inline __attribute__((always_inline)) int init_vy(unsigned int i)
{
    /*
     * Old version:
     *     return (i & 2u) ? 1 : -1;
     *
     * Branchless:
     *     bit 1 = 0 -> -1
     *     bit 1 = 1 ->  1
     */
    return (int)(((i >> 1) & 1u) << 1) - 1;
}

static inline __attribute__((always_inline)) int body_mass(unsigned int i)
{
    return 1 + (int)(i & 3u);
}

static inline __attribute__((always_inline)) int force_weight(int dx, int dy)
{
    int dist = iabs_int(dx) + iabs_int(dy);

    /*
     * Branchless equivalent of:
     *
     *   if (dist < 32)      return 4;
     *   else if (dist < 96) return 2;
     *   else                return 1;
     *
     * lt32 = 1 when dist < 32, else 0
     * lt96 = 1 when dist < 96, else 0
     *
     * dist < 32  -> 1 + 1 + 2 = 4
     * dist < 96  -> 1 + 1 + 0 = 2
     * otherwise  -> 1 + 0 + 0 = 1
     */
    int lt32 = (dist < 32);
    int lt96 = (dist < 96);

    return 1 + lt96 + (lt32 << 1);
}

__attribute__((noinline, used, patchable_function_entry(1, 0)))
void kernel_main(void)
{
    unsigned int tid = gpgpu_thread_id();

    /*
     * Host-written arguments:
     *   GPGPU_ARGS[0] = magic
     *   GPGPU_ARGS[1] = steps
     *   GPGPU_ARGS[2] = reset
     *   GPGPU_ARGS[3] = start_step, currently unused by the kernel
     *
     * Assumption: fpga.py writes valid args before every run.
     */
    int steps = GPGPU_ARGS[1];
    int reset = GPGPU_ARGS[2];

    /*
     * Branchless reset selection.
     *
     * reset_mask = 0xFFFFFFFF if reset != 0
     * reset_mask = 0x00000000 if reset == 0
     */
    int reset_mask = -nonzero_int(reset);

    int old_px = pos_x[tid];
    int old_py = pos_y[tid];
    int old_vx = vel_x[tid];
    int old_vy = vel_y[tid];

    pos_x[tid] = select_int(old_px, init_x(tid), reset_mask);
    pos_y[tid] = select_int(old_py, init_y(tid), reset_mask);
    vel_x[tid] = select_int(old_vx, init_vx(tid), reset_mask);
    vel_y[tid] = select_int(old_vy, init_vy(tid), reset_mask);

    /*
     * Loop branches are uniform if all cores execute the same program with the
     * same GPGPU_ARGS. For safest visualization/debugging, use steps-per-run=1.
     */
    for (int step = 0; step < steps; step++) {
        int xi = pos_x[tid];
        int yi = pos_y[tid];

        int ax = 0;
        int ay = 0;

        for (unsigned int j = 0; j < CORES; j++) {
            int xj = pos_x[j];
            int yj = pos_y[j];

            int dx = xj - xi;
            int dy = yj - yi;

            int w = force_weight(dx, dy) * body_mass(j);

            ax += sign_int(dx) * w;
            ay += sign_int(dy) * w;
        }

        int vx = vel_x[tid] + (ax >> 2);
        int vy = vel_y[tid] + (ay >> 2);

        int new_x = xi + vx;
        int new_y = yi + vy;

        vel_x[tid] = vx;
        vel_y[tid] = vy;
        pos_x[tid] = new_x;
        pos_y[tid] = new_y;
    }

    GPGPU_OUTPUT[(tid << 1) + 0] = pos_x[tid];
    GPGPU_OUTPUT[(tid << 1) + 1] = pos_y[tid];

    return;
}

GPGPU_START(kernel_main)

#else

#include <stdio.h>

static int pos_x[CORES];
static int pos_y[CORES];
static int vel_x[CORES];
static int vel_y[CORES];

static int nonzero_int(int x)
{
    unsigned int ux = (unsigned int)x;
    return (int)((ux | (0u - ux)) >> 31);
}

static int iabs_int(int x)
{
    int mask = x >> 31;
    return (x ^ mask) - mask;
}

static int sign_int(int x)
{
    int neg = (int)((unsigned int)x >> 31);
    int nz = nonzero_int(x);
    return nz - (neg << 1);
}

static int init_x(unsigned int i)
{
    return ((int)i * 13) - 208;
}

static int init_y(unsigned int i)
{
    return (((int)i * 29) & 255) - 128;
}

static int init_vx(unsigned int i)
{
    return (int)((i & 1u) << 1) - 1;
}

static int init_vy(unsigned int i)
{
    return (int)(((i >> 1) & 1u) << 1) - 1;
}

static int body_mass(unsigned int i)
{
    return 1 + (int)(i & 3u);
}

static int force_weight(int dx, int dy)
{
    int dist = iabs_int(dx) + iabs_int(dy);
    int lt32 = (dist < 32);
    int lt96 = (dist < 96);
    return 1 + lt96 + (lt32 << 1);
}

int main(void)
{
    int steps = 1;

    for (unsigned int tid = 0; tid < CORES; tid++) {
        pos_x[tid] = init_x(tid);
        pos_y[tid] = init_y(tid);
        vel_x[tid] = init_vx(tid);
        vel_y[tid] = init_vy(tid);
    }

    for (int step = 0; step < steps; step++) {
        int next_x[CORES];
        int next_y[CORES];
        int next_vx[CORES];
        int next_vy[CORES];

        for (unsigned int tid = 0; tid < CORES; tid++) {
            int xi = pos_x[tid];
            int yi = pos_y[tid];

            int ax = 0;
            int ay = 0;

            for (unsigned int j = 0; j < CORES; j++) {
                int dx = pos_x[j] - xi;
                int dy = pos_y[j] - yi;

                int w = force_weight(dx, dy) * body_mass(j);

                ax += sign_int(dx) * w;
                ay += sign_int(dy) * w;
            }

            next_vx[tid] = vel_x[tid] + (ax >> 2);
            next_vy[tid] = vel_y[tid] + (ay >> 2);
            next_x[tid] = xi + next_vx[tid];
            next_y[tid] = yi + next_vy[tid];
        }

        for (unsigned int tid = 0; tid < CORES; tid++) {
            pos_x[tid] = next_x[tid];
            pos_y[tid] = next_y[tid];
            vel_x[tid] = next_vx[tid];
            vel_y[tid] = next_vy[tid];
        }
    }

    printf("body,x,y\n");
    for (unsigned int tid = 0; tid < CORES; tid++) {
        printf("%u,%d,%d\n", tid, pos_x[tid], pos_y[tid]);
    }

    return 0;
}

#endif