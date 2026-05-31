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

static inline __attribute__((always_inline)) int init_z(unsigned int i)
{
    return (((int)i * 47) & 255) - 128;
}

static inline __attribute__((always_inline)) int init_vx(unsigned int i)
{
    return (int)((i & 1u) << 1) - 1;
}

static inline __attribute__((always_inline)) int init_vy(unsigned int i)
{
    return (int)(((i >> 1) & 1u) << 1) - 1;
}

static inline __attribute__((always_inline)) int init_vz(unsigned int i)
{
    return (int)(((i >> 2) & 1u) << 1) - 1;
}

static inline __attribute__((always_inline)) int body_mass(unsigned int i)
{
    return 1 + (int)(i & 3u);
}

static inline __attribute__((always_inline)) int force_weight(int dx, int dy, int dz)
{
    int dist = iabs_int(dx) + iabs_int(dy) + iabs_int(dz);
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
     * The reset flag is intentionally kept as a host-controlled switch. The demo
     * turns it on only for the first run by default; external loaders can keep it
     * off after preloading DMEM/state for custom datasets.
     */
    int steps = GPGPU_ARGS[1];
    int reset = GPGPU_ARGS[2];
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

            int w = force_weight(dx, dy, dz) * body_mass(j);

            ax += sign_int(dx) * w;
            ay += sign_int(dy) * w;
            az += sign_int(dz) * w;
        }

        int vx = vel_x[tid] + (ax >> 2);
        int vy = vel_y[tid] + (ay >> 2);
        int vz = vel_z[tid] + (az >> 2);

        pos_x[tid] = xi + vx;
        pos_y[tid] = yi + vy;
        pos_z[tid] = zi + vz;
        vel_x[tid] = vx;
        vel_y[tid] = vy;
        vel_z[tid] = vz;
    }

    GPGPU_OUTPUT[(tid * 3) + 0] = pos_x[tid];
    GPGPU_OUTPUT[(tid * 3) + 1] = pos_y[tid];
    GPGPU_OUTPUT[(tid * 3) + 2] = pos_z[tid];

    return;
}

GPGPU_START(kernel_main)

#else

#include <stdio.h>

static int pos_x[CORES];
static int pos_y[CORES];
static int pos_z[CORES];
static int vel_x[CORES];
static int vel_y[CORES];
static int vel_z[CORES];

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

static int init_z(unsigned int i)
{
    return (((int)i * 47) & 255) - 128;
}

static int init_vx(unsigned int i)
{
    return (int)((i & 1u) << 1) - 1;
}

static int init_vy(unsigned int i)
{
    return (int)(((i >> 1) & 1u) << 1) - 1;
}

static int init_vz(unsigned int i)
{
    return (int)(((i >> 2) & 1u) << 1) - 1;
}

static int body_mass(unsigned int i)
{
    return 1 + (int)(i & 3u);
}

static int force_weight(int dx, int dy, int dz)
{
    int dist = iabs_int(dx) + iabs_int(dy) + iabs_int(dz);
    int lt32 = (dist < 32);
    int lt96 = (dist < 96);
    return 1 + lt96 + (lt32 << 1);
}

static void print_csv_header(void)
{
    printf("step");
    for (unsigned int body = 0; body < CORES; body++) {
        printf(",x%u,y%u,z%u", body, body, body);
    }
    printf("\n");
}

static void print_csv_row(int step)
{
    printf("%d", step);
    for (unsigned int body = 0; body < CORES; body++) {
        printf(",%d,%d,%d", pos_x[body], pos_y[body], pos_z[body]);
    }
    printf("\n");
}

int main(void)
{
    int steps = 100000;

    for (unsigned int tid = 0; tid < CORES; tid++) {
        pos_x[tid] = init_x(tid);
        pos_y[tid] = init_y(tid);
        pos_z[tid] = init_z(tid);
        vel_x[tid] = init_vx(tid);
        vel_y[tid] = init_vy(tid);
        vel_z[tid] = init_vz(tid);
    }

    print_csv_header();

    for (int step = 1; step <= steps; step++) {
        int next_x[CORES];
        int next_y[CORES];
        int next_z[CORES];
        int next_vx[CORES];
        int next_vy[CORES];
        int next_vz[CORES];

        for (unsigned int tid = 0; tid < CORES; tid++) {
            int xi = pos_x[tid];
            int yi = pos_y[tid];
            int zi = pos_z[tid];

            int ax = 0;
            int ay = 0;
            int az = 0;

            for (unsigned int j = 0; j < CORES; j++) {
                int dx = pos_x[j] - xi;
                int dy = pos_y[j] - yi;
                int dz = pos_z[j] - zi;

                int w = force_weight(dx, dy, dz) * body_mass(j);

                ax += sign_int(dx) * w;
                ay += sign_int(dy) * w;
                az += sign_int(dz) * w;
            }

            next_vx[tid] = vel_x[tid] + (ax >> 2);
            next_vy[tid] = vel_y[tid] + (ay >> 2);
            next_vz[tid] = vel_z[tid] + (az >> 2);
            next_x[tid] = xi + next_vx[tid];
            next_y[tid] = yi + next_vy[tid];
            next_z[tid] = zi + next_vz[tid];
        }

        for (unsigned int tid = 0; tid < CORES; tid++) {
            pos_x[tid] = next_x[tid];
            pos_y[tid] = next_y[tid];
            pos_z[tid] = next_z[tid];
            vel_x[tid] = next_vx[tid];
            vel_y[tid] = next_vy[tid];
            vel_z[tid] = next_vz[tid];
        }

        print_csv_row(step);
    }

    return 0;
}

#endif
