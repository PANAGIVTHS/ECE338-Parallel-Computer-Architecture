#ifndef nbody_h
#define nbody_h
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
#endif // nbody_h