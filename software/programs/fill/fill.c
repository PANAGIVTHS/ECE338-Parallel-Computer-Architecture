/*
 * fill: a one-pixel checkerboard of two colors over a framebuffer
 * (fill_color in fill.h).
 *
 * Block y of the grid draws row y: each store writes the 32 lanes' pixels,
 * 32 neighbours, one DDR burst. Launch it over gpgpu_dim3(1, height).
 */
#include "gpgpu_device.h"
#include "fill.h"

GPGPU_GLOBAL void fill(unsigned int *fb, unsigned int width, unsigned int c0, unsigned int c1)
{
    unsigned int y = gpgpu_block_idx_y();
    volatile unsigned int *row = fb + y * width;

    /* The loop is the same for every lane: width is a multiple of the lanes. */
    for (unsigned int x0 = 0; x0 < width; x0 += gpgpu_block_dim()) {
        unsigned int x = x0 + gpgpu_thread_idx();

        row[x] = fill_color(x, y, c0, c1);
    }
}
