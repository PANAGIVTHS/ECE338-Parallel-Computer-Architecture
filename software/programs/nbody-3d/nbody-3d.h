#ifndef nbody_3d_h
#define nbody_3d_h

/* What the kernel (nbody-3d.c) and the host program (host.c) share: the
 * initial bodies and the force between two. Branch-free: lanes branch with
 * lane 0. */

#include "gpgpu_types.h"

/* One body per lane of a block. */
#define NBODIES GPGPU_NUM_CORES

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

static inline __attribute__((always_inline)) int force_weight(int dx, int dy, int dz)
{
    int dist = iabs_int(dx) + iabs_int(dy) + iabs_int(dz);
    int lt32 = (dist < 32);
    int lt96 = (dist < 96);
    return 1 + lt96 + (lt32 << 1);
}
/* Body i's mass: 1 to 4, as in datasets/default.json. */
static inline __attribute__((always_inline)) int init_mass(unsigned int i)
{
    return 1 + (int)(i & 3u);
}

/* The acceleration (times 4) of the body at (xi, yi, zi) from all the bodies. */
static inline __attribute__((always_inline)) void nbody_3d_accel(int xi, int yi, int zi, const volatile int *pos_x,
                                                                 const volatile int *pos_y, const volatile int *pos_z,
                                                                 const volatile int *mass, int a[3])
{
    int ax = 0, ay = 0, az = 0;

    for (unsigned int j = 0; j < NBODIES; j++) {
        int dx = pos_x[j] - xi;
        int dy = pos_y[j] - yi;
        int dz = pos_z[j] - zi;
        int w = force_weight(dx, dy, dz) * mass[j];

        ax += sign_int(dx) * w;
        ay += sign_int(dy) * w;
        az += sign_int(dz) * w;
    }
    a[0] = ax;
    a[1] = ay;
    a[2] = az;
}

/* a / 4, rounded towards zero. */
static inline __attribute__((always_inline)) int quarter(int a)
{
    return (a + ((a >> 31) & 3)) >> 2;
}

#endif