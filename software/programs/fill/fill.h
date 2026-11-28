#ifndef FILL_H
#define FILL_H

/* What the kernel (fill.c) and the host program (host.c) share: the color of
 * a pixel. */

#include "gpgpu_types.h"

/*
 * A one-pixel checkerboard of two colors: c0 where x + y is even, c1 where
 * it is odd. c0 == c1 fills the framebuffer with one color; black and white
 * give the most TMDS transitions per pixel. Branches follow lane 0, so the
 * parity selects the color by a multiply (0 or 1) instead of an if.
 */
static inline unsigned int fill_color(unsigned int x, unsigned int y, unsigned int c0, unsigned int c1)
{
    unsigned int odd = (x + y) & 1u;

    /* Hides that odd is 0 or 1, so GCC keeps the multiply instead of
     * turning the select back into a branch. */
    __asm__ volatile("" : "+r"(odd));
    return c0 ^ ((c0 ^ c1) * odd);
}

#endif /* FILL_H */
