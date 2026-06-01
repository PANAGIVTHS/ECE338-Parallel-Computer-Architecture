#ifndef mandelbrot_h
#define mandelbrot_h

#define WIDTH 64
#define HEIGHT 64
#define LOG2_WIDTH 6

/*
 * Fixed-point format: Q13
 *
 * 1.0 = 8192
 * 2.0 = 16384
 * 4.0 = 32768
 *
 * Q13 gives more zoom precision than Q10. With WIDTH=64, the pixel step is:
 *
 *     pixel_step_q = scale_q >> 6
 *
 * so the zoom stops changing only when scale_q < 64, i.e. viewport scale
 * smaller than 64 / 8192 = 0.0078125.
 */
#define FP_SHIFT 13
#define FP_ONE (1 << FP_SHIFT)

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
#define DEFAULT_CENTER_RE_Q (-6092)   /* -0.74365 * 8192 */
#define DEFAULT_CENTER_IM_Q (1080)    /*  0.13184 * 8192 */
#define DEFAULT_SCALE_Q     (24576)   /*  3.00000 * 8192 */

/*
 * For x86 CSV generation only.
 */
#define DEFAULT_FRAMES 1000
#define DEFAULT_ZOOM_NUM 9941
#define DEFAULT_ZOOM_DEN 10000

static inline int select_int(int old_value, int new_value, int mask)
{
    return (old_value & ~mask) | (new_value & mask);
}

static inline int fixed_mul(int a, int b)
{
    return (a * b) >> FP_SHIFT;
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

        escape_iter = select_int(escape_iter, iter, new_escape_mask);

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
         * This is important with Q13: an escaped z can be much larger than 2,
         * and repeatedly squaring it could overflow 32-bit integers. We no
         * longer need z after escape_iter has been recorded, so zeroing it is
         * safe and keeps the arithmetic bounded.
         */
        int update_mask = -(escaped ^ 1);

        zr = select_int(0, zr_next, update_mask);
        zi = select_int(0, zi_next, update_mask);
    }

    return escape_iter;
}

#endif // mandelbrot_h