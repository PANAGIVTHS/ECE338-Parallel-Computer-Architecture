#ifndef PIXELS_H
#define PIXELS_H

/* What the kernel (pixels.c) and the host program (host.c) share: the color of
 * a pixel. */

#include "gpgpu_types.h"

/* XRGB8888: 0x00RRGGBB. GREEN is RED >> 8 and BLUE is RED >> 16. */
#define PIXELS_RED 0x00FF0000u

/*
 * Three vertical bars: red, green, blue. Branches follow lane 0, so each lane
 * computes its color without an if: bar = 0, 1 or 2 shifts RED down to GREEN
 * or BLUE. (A mask select compiles back into a branch at -O2.) Comparing 3x
 * against the width avoids width / 3: the GPU runs only MUL of the M
 * extension, and GCC turns the division into MULHU.
 */
static inline unsigned int bar_color(unsigned int x, unsigned int width)
{
    unsigned int bar = (3 * x >= width) + (3 * x >= 2 * width);

    return PIXELS_RED >> (8 * bar);
}

#endif /* PIXELS_H */
