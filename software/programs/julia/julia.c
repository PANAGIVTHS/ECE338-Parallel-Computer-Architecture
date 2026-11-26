/*
 * julia: one frame of the animated Julia set (julia.h, drawn by
 * fractal_render in mandelbrot.h). The host computes the frame's view.
 */
#include "julia.h"

#ifdef __riscv

/* The view, which the host writes before each frame (julia_setup in julia.h). */
GPGPU_DEVICE fractal_t view;

/* Shared memory: the view, for the escape loop; each lane's sample, for its
 * neighbours to read. Every lane writes the same view. */
GPGPU_SHARED volatile fractal_t local_view;
GPGPU_SHARED volatile unsigned int samples[GPGPU_NUM_CORES];

GPGPU_GLOBAL void julia(unsigned int *fb, int width, int height, int frame, const fractal_t *view)
{
    fractal_render(fb, width, height, frame, view, &local_view, samples);
}

#endif
