/*
 * metaballs: one frame of the blobs of metaballs.h.
 *
 * Block y of the grid draws row y: launch it over gpgpu_dim3(1, height). The
 * host computes the frame's ball positions (ball_positions) and passes them
 * in a GPGPU_DEVICE table. Each store writes 32 neighbouring pixels, one DDR
 * burst.
 */
#include "gpgpu_device.h"
#include "metaballs.h"

GPGPU_DEVICE balls_t balls;

GPGPU_GLOBAL void metaballs(unsigned int *fb, int width, const balls_t *b)
{
    int y = (int)gpgpu_block_idx_y();
    volatile unsigned int *row = fb + y * width;
    int reach[BALLS];
    int bx[BALLS];

#pragma GCC unroll 8
    for (int i = 0; i < BALLS; i++) {
        reach[i] = ball_reach(b->r2[i], y - b->y[i]);
        bx[i] = b->x[i];
    }

    int tid = (int)gpgpu_thread_idx();
    for (int x = tid; x < width + tid; x += CORES) {
        int field = 0;

#pragma GCC unroll 8
        for (int i = 0; i < BALLS; i++)
            field += ball_field(reach[i], x - bx[i]);
        row[x] = field_color(field, y);
    }
}
