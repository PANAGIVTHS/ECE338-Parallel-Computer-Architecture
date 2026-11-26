/*
 * cube: one frame of the spinning cube of cube.h.
 *
 * The host runs cube_setup() for the frame and passes the result in a
 * GPGPU_DEVICE cube_t. One block draws the whole frame: launch it over
 * gpgpu_dim3(1). It copies the cube into shared memory first, because every
 * row reads the faces' edges again. Per row, every lane turns each visible
 * face's edges into a span of pixels; per pixel, it only tests its x against
 * the spans and selects the color with masks, so lanes never diverge, and
 * each store writes 32 consecutive pixels (one DDR burst).
 */
#include "gpgpu_device.h"
#include "cube.h"

GPGPU_DEVICE cube_t frame_cube;

/* The cube in shared memory; every lane writes the same words. */
GPGPU_SHARED volatile cube_t cube;

GPGPU_GLOBAL void cube_kernel(unsigned int *fb, int width, int height, const cube_t *src)
{
    const volatile int *from = (const volatile int *)src;
    volatile int *to = (volatile int *)&cube;

    for (unsigned int i = 0; i < sizeof(cube_t) / sizeof(int); i++)
        to[i] = from[i];
    gpgpu_syncthreads();

    for (int y = 0; y < height; y++) {
        int xl[SLOTS], w[SLOTS];
        unsigned int color[SLOTS];

#pragma GCC unroll 4
        for (int s = 0; s < SLOTS; s++) {
            face_span(&cube, s, y, &xl[s], &w[s]);
            color[s] = cube.slot[s].color;
        }

        int tid = (int)gpgpu_thread_idx();
        unsigned int bg = background(y);
        volatile unsigned int *row = fb + y * width;

        for (int x = tid; x < width + tid; x += CORES) {
            unsigned int c = bg;

#pragma GCC unroll 4
            for (int s = 0; s < SLOTS; s++)
                c = (unsigned int)select_mask(in_span(x, xl[s], w[s]), (int)color[s], (int)c);
            row[x] = c;
        }
    }
}
