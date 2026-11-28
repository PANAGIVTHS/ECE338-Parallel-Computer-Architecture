#ifndef RIPPLE_H
#define RIPPLE_H

/* What the kernel (ripple.c) and the host program (host.c) share: the color
 * of a pixel. */

#include "gpgpu_types.h"

/*
 * An animated test pattern for measuring frame rate: red rings ripple out of
 * the centre, green and blue XOR patterns scroll across it.
 *
 * Lanes branch with lane 0, so the pixel color is computed straight through
 * (no if, no ?:). It uses only add, sub, xor, and, shifts and MUL: the GPU has
 * no divider and no high multiply.
 */
static inline unsigned int ripple_color(unsigned int x, unsigned int y, unsigned int width, unsigned int height,
                                        unsigned int frame)
{
    int dx = (int)x - (int)(width >> 1);
    int dy = (int)y - (int)(height >> 1);
    unsigned int distance2 = (unsigned int)(dx * dx + dy * dy);

    unsigned int red = ((distance2 >> 8) - 4u * frame) & 0xFFu;
    unsigned int green = ((x + frame) ^ y) & 0xFFu;
    unsigned int blue = (x ^ (y + 2u * frame)) & 0xFFu;

    return (red << 16) | (green << 8) | blue; /* 0x00RRGGBB */
}

#endif /* RIPPLE_H */
