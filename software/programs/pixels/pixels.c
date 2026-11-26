/*
 * pixels: three vertical bars, red, green and blue (bar_color in pixels.h).
 *
 * Block y of the grid draws row y: each store writes the 32 lanes' pixels,
 * 32 neighbours, one DDR burst. Launch it over gpgpu_dim3(1, height).
 */
#include "gpgpu_device.h"
#include "pixels.h"

GPGPU_GLOBAL void pixels(unsigned int *fb, unsigned int width)
{
    volatile unsigned int *row = fb + gpgpu_block_idx_y() * width;

    /* The loop is the same for every lane: width is a multiple of the lanes. */
    for (unsigned int x0 = 0; x0 < width; x0 += gpgpu_block_dim()) {
        unsigned int x = x0 + gpgpu_thread_idx();

        row[x] = bar_color(x, width);
    }
}
