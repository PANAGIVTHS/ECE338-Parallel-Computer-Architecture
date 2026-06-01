#ifndef nbody_3d_h
#define nbody_3d_h
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
#endif