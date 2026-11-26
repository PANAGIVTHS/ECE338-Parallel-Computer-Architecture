#ifndef JULIA_H
#define JULIA_H

/* What the kernel (julia.c) and the host program (host.c) share: the fractal
 * code of mandelbrot.h and the view of each frame. */

#include "gpgpu_math.h"
#include "../mandelbrot/mandelbrot.h"

/*
 * Animated Julia set: z -> z^2 + c with z starting at the pixel and c moving
 * around a circle of radius 0.7885, so the fractal morphs from frame to
 * frame. The palette cycles with the frame as well.
 *
 * mandelbrot.h draws it: every pixel runs all JULIA_ITER iterations (no early
 * exit, so no divergence), in Q20 fixed point, one sample per 2x2 pixels.
 */

/* Iterations per sample; the cost of a frame is close to proportional. */
#define JULIA_ITER 32

/* c = JULIA_C_RADIUS * e^(i a), with a advancing JULIA_C_STEP phase units
 * (TURN per turn) per frame. Q20. */
#define JULIA_C_RADIUS 826800 /* 0.7885 */
#define JULIA_C_STEP 4

/* Distance between pixels in the complex plane, Q20 (3.3 across 1280
 * pixels), breathing by JULIA_ZOOM_SWING with the frame. */
#define JULIA_PIXEL_STEP 2700
#define JULIA_ZOOM_SWING 300

INLINE void julia_setup(volatile fractal_t *f, int frame)
{
    int a = frame * JULIA_C_STEP;

    f->julia = 1;
    /* Split the radius's shift so the product stays in 31 bits. */
    f->cx = ((JULIA_C_RADIUS >> 4) * cosine_q14(a)) >> 10;
    f->cy = ((JULIA_C_RADIUS >> 4) * sine_q14(a)) >> 10;
    f->step = JULIA_PIXEL_STEP + ((JULIA_ZOOM_SWING * sine_q14(frame * 3)) >> 14);
    f->max_iter = JULIA_ITER;
}

#endif /* JULIA_H */
