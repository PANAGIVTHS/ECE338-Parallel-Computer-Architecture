#include "../gpgpu_runtime.h"
#include "../gpgpu_math.h"
#include "mandelbrot.h"

/*
 * Endless Mandelbrot zoom: from the whole set down to the small copy of it
 * on the antenna at (-1.7685, 0), then over again.
 *
 * Each frame shrinks the view by 1/2^MANDEL_ZOOM_SHIFT, for MANDEL_ZOOM_FRAMES
 * frames (about 7.6x). That is about as deep as Q20 with the pre-shifted
 * multiply goes before the picture turns blocky (see mandelbrot.h). The
 * view's center moves from the whole set's to the copy's as the zoom goes,
 * so the copy glides into the middle while it grows. The palette cycles with
 * the frame.
 *
 * mandelbrot.h draws it: every pixel runs all MANDEL_ITER iterations (no
 * early exit, so no divergence), one sample per 2x2 pixels.
 */

/* Iterations per sample; the cost of a frame is close to proportional. */
#define MANDEL_ITER 32

/* Centers, Q20: the whole set's (-0.75, 0) and the copy's (-1.7685, 0). */
#define MANDEL_START_RE (-786432)
#define MANDEL_START_IM 0
#define MANDEL_TARGET_RE (-1854407)
#define MANDEL_TARGET_IM 0

/* Pixel step at the start of each zoom: 2.5 across 1280 pixels, Q20. */
#define MANDEL_START_STEP 2048

/* Frames per zoom (a power of two: frame & (MANDEL_ZOOM_FRAMES - 1) picks
 * the frame within it), and the step shrinks by step >> MANDEL_ZOOM_SHIFT
 * per frame: (31/32)^63 = 1 / 7.4 at the last frame. */
#define MANDEL_ZOOM_FRAMES 64
#define MANDEL_ZOOM_SHIFT 5

/* The share of the way left to go, as (step - end) / (start - end), in Q12. */
#define MANDEL_BLEND_SHIFT 12

INLINE void mandel_setup(volatile fractal_t *f, int frame)
{
    int k = frame & (MANDEL_ZOOM_FRAMES - 1);
    int step = MANDEL_START_STEP, end = MANDEL_START_STEP;

    /* The same counts in every lane. */
    for (int i = 1; i < MANDEL_ZOOM_FRAMES; i++) {
        end -= end >> MANDEL_ZOOM_SHIFT;
        if (i == k)
            step = end;
    }

    /* (start - target) / 4 * left stays under 2^31 for the centers above;
     * the / 4 costs 2 of 20 fraction bits. */
    int left = (int)udiv_uniform((unsigned int)(step - end) << MANDEL_BLEND_SHIFT,
                                 (unsigned int)(MANDEL_START_STEP - end));

    f->julia = 0;
    f->cx = MANDEL_TARGET_RE +
            ((((MANDEL_START_RE - MANDEL_TARGET_RE) >> 2) * left) >> (MANDEL_BLEND_SHIFT - 2));
    f->cy = MANDEL_TARGET_IM +
            ((((MANDEL_START_IM - MANDEL_TARGET_IM) >> 2) * left) >> (MANDEL_BLEND_SHIFT - 2));
    f->step = step;
    f->max_iter = MANDEL_ITER;
}

#ifdef __riscv

/* Every lane writes the same values each frame. */
static volatile fractal_t view;

/* Each lane's sample, for its neighbors to read. */
static volatile unsigned int samples[GPGPU_NUM_CORES];

void main(void)
{
    /* Args: see fractal_render() in mandelbrot.h. */
    mandel_setup(&view, GPGPU_ARGS[3]);
    fractal_render(&view, samples);

    return;
}

GPGPU_START(main)

#else

#include <stdlib.h>

/* ./mandelbrot_x86 width height frame > mandelbrot.ppm writes that frame. */
int main(int argc, char **argv)
{
    if (argc != 4) {
        fprintf(stderr, "usage: %s width height frame\n", argv[0]);
        return 1;
    }

    int width = (int)strtol(argv[1], NULL, 0);
    int height = (int)strtol(argv[2], NULL, 0);
    int frame = (int)strtol(argv[3], NULL, 0);
    fractal_t view;

    mandel_setup(&view, frame);
    fractal_ppm(&view, width, height, frame);
    return 0;
}

#endif
