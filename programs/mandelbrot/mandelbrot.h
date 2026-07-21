#ifndef mandelbrot_h
#define mandelbrot_h

#define WIDTH 64
#define HEIGHT 64
#define LOG2_WIDTH 6

/*
 * Fixed-point format: Q20
 *
 * 1.0 = 1048576
 * 2.0 = 2097152
 * 4.0 = 4194304
 *
 * Q20 gives enough zoom precision for the default 1000-frame x86 animation.
 * With WIDTH=64, the center-to-center pixel step is roughly:
 *
 *     pixel_step_q = scale_q >> 6
 *
 * Q13 stopped visibly changing once scale_q was clamped at 64. Q20 moves that
 * quantization limit 128x deeper while still keeping coordinates in the 26-bit
 * packed argument field used by the FPGA adapter.
 */
#define FP_SHIFT 20
#define FP_ONE (1 << FP_SHIFT)

/*
 * Keep multiplication in 32-bit arithmetic for the RV32/GPU path. Shifting both
 * operands down before the multiply avoids overflow for escaped z values; the
 * result still has Q20 scale, with about Q16 effective multiply precision.
 */
#define FP_MUL_PRE_SHIFT 8

#define MAX_ITER 64
#define ESCAPE_RADIUS2_Q (4 << FP_SHIFT)

/*
 * Boundary-focused Mandelbrot viewport.
 *
 * The old default center (-0.75, 0.0) lies inside the black Mandelbrot set, so
 * zooming there quickly becomes black. This center is near the Seahorse Valley
 * boundary, so zooming reveals fractal detail.
 *
 * Approximate real values:
 *   center_re ~= -0.74365
 *   center_im ~=  0.13184
 *   scale     =   3.0
 */
#define DEFAULT_CENTER_RE_Q (-779776)  /* old Q13 -6092 converted to Q20 */
#define DEFAULT_CENTER_IM_Q (138240)   /* old Q13  1080 converted to Q20 */
#define DEFAULT_SCALE_Q     (3145728)  /* 3.00000 * 1048576 */

/*
 * For x86 CSV generation only. The zoom update uses scale -= scale >> 7, so it
 * has no division and maps cleanly to the current RV32/GPU instruction subset.
 */
#define DEFAULT_FRAMES 1000
#define DEFAULT_ZOOM_SHIFT 7

static inline int select_int(int old_value, int new_value, int mask)
{
    return (old_value & ~mask) | (new_value & mask);
}

static inline int fixed_mul(int a, int b)
{
    return ((a >> FP_MUL_PRE_SHIFT) * (b >> FP_MUL_PRE_SHIFT)) >>
           (FP_SHIFT - (2 * FP_MUL_PRE_SHIFT));
}

static inline int zoom_next_scale(int scale_q)
{
    int delta = scale_q >> DEFAULT_ZOOM_SHIFT;
    int delta_is_zero = (delta == 0);
    delta = select_int(delta, 1, -delta_is_zero);

    int next = scale_q - delta;
    int below_min = (next < 1);
    return select_int(next, 1, -below_min);
}

/*
 * Branchless Mandelbrot pixel.
 *
 * Every pixel executes exactly MAX_ITER iterations.
 * There is no early exit, so there is no divergence from the escape condition.
 */
static inline int mandel_pixel(
    unsigned int px,
    unsigned int py,
    int center_re_q,
    int center_im_q,
    int scale_q
)
{
    int x_off = (int)px - (WIDTH >> 1);
    int y_off = (int)py - (HEIGHT >> 1);

    int cx = center_re_q + ((x_off * scale_q) >> LOG2_WIDTH);
    int cy = center_im_q + ((y_off * scale_q) >> LOG2_WIDTH);

    int zr = 0;
    int zi = 0;

    int escaped = 0;
    int escape_iter = MAX_ITER;

    for (int iter = 0; iter < MAX_ITER; iter++) {
        int zr2 = fixed_mul(zr, zr);
        int zi2 = fixed_mul(zi, zi);
        int mag2 = zr2 + zi2;

        /*
         * escaped_now = 1 if |z|^2 > 4, else 0.
         * This should compile to a compare instruction, not a branch.
         */
        int escaped_now = (mag2 > ESCAPE_RADIUS2_Q);

        int active = escaped ^ 1;
        int new_escape = active & escaped_now;
        int new_escape_mask = -new_escape;
        volatile int keep_escape_iter_mask = ~new_escape_mask;
        volatile int set_escape_iter_mask = new_escape_mask;

        escape_iter = (escape_iter & keep_escape_iter_mask) |
                      (iter & set_escape_iter_mask);

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
        int update_mask = -(escaped ^ 1);

        zr = zr_next & update_mask;
        zi = zi_next & update_mask;
    }

    return escape_iter;
}

#endif // mandelbrot_h