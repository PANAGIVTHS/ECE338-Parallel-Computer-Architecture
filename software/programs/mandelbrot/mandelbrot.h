#ifndef mandelbrot_h
#define mandelbrot_h

#include "../gpgpu_math.h"

/*
 * Escape-time fractals (mandelbrot, julia) drawn into a framebuffer.
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

#ifdef __riscv

#include "../gpgpu_runtime.h"

/*
 * Draw one frame of *f into the framebuffer, then advance the frame counter.
 *
 * Args (the ripple convention):
 *   GPGPU_ARGS[0] = framebuffer base, byte address (GPGPU_FB0_BASE or GPGPU_FB1_BASE)
 *   GPGPU_ARGS[1] = width in pixels, a multiple of 2 * GPGPU_NUM_CORES
 *   GPGPU_ARGS[2] = height in pixels, even
 *   GPGPU_ARGS[3] = frame number
 *
 * Each sample colors a 2x2 block: lane j computes the sample of pixels
 * x0 + 2j, x0 + 2j + 1 in rows y and y + 1, and the lanes swap samples
 * through `samples` in DMEM so each store still writes GPGPU_NUM_CORES
 * consecutive pixels (one DDR burst). That is a quarter of the escape loops
 * of full resolution.
 *
 * Each lane's stack is only GPGPU_STACK_STRIDE bytes, too small for the
 * spills of this loop nest. So the loops keep only y and x0 in registers
 * across the escape loop: the arguments are reloaded (GPGPU_ARGS is
 * volatile) and *f is in DMEM.
 */
INLINE void fractal_render(volatile const fractal_t *f, volatile unsigned int *samples)
{
    const int cores = (int)GPGPU_NUM_CORES;

    for (int y = 0; y < GPGPU_ARGS[2]; y += FRACTAL_BLOCK) {
        for (int x0 = 0; x0 < GPGPU_ARGS[1]; x0 += FRACTAL_BLOCK * cores) {
            int tid = (int)gpgpu_thread_id();

            samples[tid] = fractal_sample(x0 + FRACTAL_BLOCK * tid, y, GPGPU_ARGS[1],
                                          GPGPU_ARGS[2], GPGPU_ARGS[3], f);

            /* The store above completes in every lane before these loads:
             * the warp waits for all lanes' responses to each access.
             * Output pixel x0 + tid shows sample tid / 2, and x0 + cores +
             * tid shows sample cores / 2 + tid / 2. */
            tid = (int)gpgpu_thread_id();
            unsigned int a = samples[tid >> 1];
            unsigned int b = samples[(cores >> 1) + (tid >> 1)];
            int width = GPGPU_ARGS[1];
            volatile unsigned int *p =
                (volatile unsigned int *)(uintptr_t)GPGPU_ARGS[0] + y * width + x0 + tid;

            p[0] = a;
            p[cores] = b;
            p[width] = a;
            p[width + cores] = b;
        }
    }

    /* Every lane stores the same value. */
    GPGPU_ARGS[3] = GPGPU_ARGS[3] + 1;
}

#else

#include <stdio.h>

/* The x86 reference: the same frame as a binary PPM on stdout. */
static void fractal_ppm(const fractal_t *f, int width, int height, int frame)
{
    printf("P6\n%d %d\n255\n", width, height);
    for (int y = 0; y < height; y++) {
        for (int x = 0; x < width; x++) {
            /* The sample of the 2x2 block the pixel is in. */
            unsigned int color = fractal_sample(x & ~(FRACTAL_BLOCK - 1), y & ~(FRACTAL_BLOCK - 1),
                                                width, height, frame, f);

            putchar((color >> 16) & 0xFF);
            putchar((color >> 8) & 0xFF);
            putchar(color & 0xFF);
        }
    }
}

#endif

#endif // mandelbrot_h
