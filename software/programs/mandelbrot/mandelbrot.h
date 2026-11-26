#ifndef mandelbrot_h
#define mandelbrot_h

#include "gpgpu_math.h"

/*
 * Escape-time fractals (mandelbrot, julia) drawn into a framebuffer. The host
 * computes each frame's view (fractal_t) and checks frames with
 * fractal_sample(); the kernel draws them with fractal_render().
 *
 * Fixed-point format: Q20 (1.0 = 1048576).
 *
 * Keep multiplication in 32-bit arithmetic for the RV32/GPU path. Shifting both
 * operands down before the multiply avoids overflow for escaped z values; the
 * result still has Q20 scale, with about Q12 effective multiply precision. That
 * limits zooming: below a pixel step of about 2^-12 the picture turns blocky.
 */
#define FP_SHIFT 20
#define FP_ONE (1 << FP_SHIFT)
#define FP_MUL_PRE_SHIFT 8

#define ESCAPE_RADIUS2_Q (4 << FP_SHIFT)

/* Samples are 2x2 pixels: one per lane in each chunk of 2 * CORES pixels. */
#define FRACTAL_BLOCK 2

INLINE int fixed_mul(int a, int b)
{
    return ((a >> FP_MUL_PRE_SHIFT) * (b >> FP_MUL_PRE_SHIFT)) >>
           (FP_SHIFT - (2 * FP_MUL_PRE_SHIFT));
}

/*
 * Branchless escape time of z -> z^2 + c from z = (zr, zi).
 *
 * Every pixel executes exactly max_iter iterations.
 * There is no early exit, so there is no divergence from the escape condition.
 * Returns the iteration at which |z|^2 first exceeded 4, or max_iter.
 */
INLINE int escape_time(int zr, int zi, int cx, int cy, int max_iter)
{
    int escaped = 0;
    int escape_iter = max_iter;

    for (int iter = 0; iter < max_iter; iter++) {
        int zr2 = fixed_mul(zr, zr);
        int zi2 = fixed_mul(zi, zi);
        int mag2 = zr2 + zi2;

        /* escaped_now = 1 if |z|^2 > 4, else 0: a compare, not a branch. */
        int escaped_now = (mag2 > ESCAPE_RADIUS2_Q);

        int active = escaped ^ 1;
        int new_escape_mask = mask_of(active & escaped_now);

        escape_iter = select_mask(new_escape_mask, iter, escape_iter);

        escaped = escaped | escaped_now;

        /*
         * z_next = z^2 + c
         *
         * zr_next = zr^2 - zi^2 + cx
         * zi_next = 2*zr*zi + cy
         */
        int zrzi = fixed_mul(zr, zi);
        int zr_next = zr2 - zi2 + cx;
        int zi_next = (zrzi << 1) + cy;

        /*
         * Once a pixel has escaped, set z to 0 instead of freezing it.
         *
         * This is important with Q20: an escaped z can be much larger than 2,
         * and repeatedly squaring it could overflow 32-bit integers. We no
         * longer need z after escape_iter has been recorded, so zeroing it is
         * safe and keeps the arithmetic bounded.
         */
        int update_mask = mask_of(escaped ^ 1);

        zr = zr_next & update_mask;
        zi = zi_next & update_mask;
    }

    return escape_iter;
}

/* One frame's view. The pixel p (relative to the screen center, times step)
 * goes into z for a Julia set (c fixed at (cx, cy)) and into c for the
 * Mandelbrot set (z starting at 0, c = (cx, cy) + p). */
typedef struct {
    int julia;  /* 1: Julia set, 0: Mandelbrot set */
    int cx, cy; /* Q20 */
    int step;   /* distance between pixels, Q20 */
    int max_iter;
} fractal_t;

/* Color of the sample at pixel (px, py): black inside the set, outside a
 * rainbow by escape time that cycles with the frame and fades out towards
 * the background. */
INLINE unsigned int fractal_sample(int px, int py, int width, int height, int frame,
                                   volatile const fractal_t *f)
{
    int pr = (px - (width >> 1)) * f->step;
    int pi = (py - (height >> 1)) * f->step;
    int n;

    if (f->julia) /* the same in every lane */
        n = escape_time(pr, pi, f->cx, f->cy, f->max_iter);
    else
        n = escape_time(0, 0, f->cx + pr, f->cy + pi, f->max_iter);

    int t = n * 40 + frame * 6;
    int level = min255(n * 24 + 16);
    int outside = mask_of(n != f->max_iter);
    int r = 128 + ((127 * sine_q14(t)) >> 14);
    int g = 128 + ((127 * sine_q14(t + TURN / 3)) >> 14);
    int b = 128 + ((127 * sine_q14(t + 2 * TURN / 3)) >> 14);

    r = ((r * level) >> 8) & outside;
    g = ((g * level) >> 8) & outside;
    b = ((b * level) >> 8) & outside;
    return ((unsigned int)r << 16) | ((unsigned int)g << 8) | (unsigned int)b;
}

/* ---- The Mandelbrot zoom (mandelbrot.c): the view of each frame ---- */

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

#include "gpgpu_device.h"

/*
 * Row pair `block_idx_y` of one frame of *view: launch over
 * gpgpu_dim3(1, height / 2). width is a multiple of 2 * GPGPU_NUM_CORES.
 *
 * Each sample colors a 2x2 block: lane j computes the sample of pixels
 * x0 + 2j, x0 + 2j + 1 in rows y and y + 1, and the lanes swap samples
 * through `samples` in shared memory so each store still writes
 * GPGPU_NUM_CORES consecutive pixels (one DDR burst). That is a quarter of
 * the escape loops of full resolution.
 *
 * The view is copied from GMEM into shared memory first (`local`), so the
 * escape loop reads it from the BRAM. Every lane stores the same values.
 */
INLINE void fractal_render(unsigned int *fb, int width, int height, int frame, const fractal_t *view,
                           volatile fractal_t *local, volatile unsigned int *samples)
{
    const int cores = (int)GPGPU_NUM_CORES;
    const int y = FRACTAL_BLOCK * (int)gpgpu_block_idx_y();

    local->julia = view->julia;
    local->cx = view->cx;
    local->cy = view->cy;
    local->step = view->step;
    local->max_iter = view->max_iter;
    gpgpu_syncthreads();

    for (int x0 = 0; x0 < width; x0 += FRACTAL_BLOCK * cores) {
        int tid = (int)gpgpu_thread_idx();

        samples[tid] = fractal_sample(x0 + FRACTAL_BLOCK * tid, y, width, height, frame, local);
        gpgpu_syncthreads();

        /* Output pixel x0 + tid shows sample tid / 2, and x0 + cores + tid
         * shows sample cores / 2 + tid / 2. */
        unsigned int a = samples[tid >> 1];
        unsigned int b = samples[(cores >> 1) + (tid >> 1)];
        volatile unsigned int *p = fb + y * width + x0 + tid;

        p[0] = a;
        p[cores] = b;
        p[width] = a;
        p[width + cores] = b;
        gpgpu_syncthreads();
    }
}

#endif

#endif // mandelbrot_h
