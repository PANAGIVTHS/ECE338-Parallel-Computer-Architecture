#ifndef GPGPU_MATH_H
#define GPGPU_MATH_H

/*
 * Branch-free integer helpers for kernels, shared with their x86 builds.
 *
 * Lanes branch with lane 0, so per-pixel choices are masks (0 or ~0), not
 * branches. The GPU has no divider and returns the low product for every
 * M-extension instruction but MUL, so these use only add, sub, logic, shifts
 * and MUL.
 */

/* Every helper must be inlined: a call needs AUIPC, which the core does not
 * decode, and a function's RET (jalr x0, 0(x1)) would end the kernel. */
#define INLINE static inline __attribute__((always_inline))

/* ~0 when cond is nonzero, else 0. The empty asm hides the mask from the
 * optimizer, so GCC cannot turn the selects that use it back into branches. */
INLINE int mask_of(int cond)
{
    int m = -(cond != 0);

    __asm__("" : "+r"(m));
    return m;
}

/* a where mask is ~0, b where it is 0. */
INLINE int select_mask(int mask, int a, int b)
{
    return b ^ ((a ^ b) & mask);
}

INLINE int abs_int(int v)
{
    int m = v >> 31;

    return (v ^ m) - m;
}

INLINE int max0(int v)
{
    return v & ~(v >> 31);
}

INLINE int min255(int v)
{
    int over = (255 - v) >> 31; /* ~0 when v > 255 */

    return (v & ~over) | (255 & over);
}

/* Phase units in one turn of sine_q14(). */
#define TURN 1024

/* sin(2 pi p / TURN) in Q14 for any p: a parabola per half turn, then the
 * usual y + 0.225 (y |y| - y) correction (error under 0.1 %). */
INLINE int sine_q14(int p)
{
    int x = (p & (TURN - 1)) - TURN / 2; /* -pi .. pi, so this is -sin */
    int y = (x * (TURN / 2 - abs_int(x))) >> 2;

    y += (((y * abs_int(y)) >> 14) - y) * 3686 >> 14;
    return -y;
}

INLINE int cosine_q14(int p)
{
    return sine_q14(p + TURN / 4);
}

/* n / d by shift and subtract (the GPU has no divider); d must be nonzero.
 * It branches on the values, so use it only on values that are the same in
 * every lane, such as per-frame setup. */
INLINE unsigned int udiv_uniform(unsigned int n, unsigned int d)
{
    unsigned int q = 0, r = 0;

    for (int i = 31; i >= 0; i--) {
        r = (r << 1) | ((n >> i) & 1u);
        if (r >= d) {
            r -= d;
            q |= 1u << i;
        }
    }
    return q;
}

/* n / d rounded toward zero, like C's /; the same restriction as above. */
INLINE int sdiv_uniform(int n, int d)
{
    unsigned int q = udiv_uniform((unsigned int)abs_int(n), (unsigned int)abs_int(d));

    return ((n ^ d) < 0) ? -(int)q : (int)q;
}

#endif /* GPGPU_MATH_H */
