/*
 * ripple: one frame of the animated pattern of ripple.h.
 *
 * Block y of the grid draws row y: launch it over gpgpu_dim3(1, height). Each
 * store writes 32 neighbouring pixels, one DDR burst. The host passes the
 * frame number; the kernel keeps no state between frames.
 */
#include "gpgpu_device.h"
#include "ripple.h"

GPGPU_GLOBAL void ripple(unsigned int *fb, unsigned int width, unsigned int height, unsigned int frame)
{
    unsigned int y = gpgpu_block_idx_y();
    volatile unsigned int *row = fb + y * width;

    for (unsigned int x0 = 0; x0 < width; x0 += gpgpu_block_dim()) {
        unsigned int x = x0 + gpgpu_thread_idx();

        row[x] = ripple_color(x, y, width, height, frame);
    }
}
