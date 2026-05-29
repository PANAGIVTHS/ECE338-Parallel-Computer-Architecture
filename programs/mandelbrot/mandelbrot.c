#include "../gpgpu_runtime.h"

#define WIDTH 64
#define HEIGHT 64
#define LOG2_WIDTH 6

#define CORES GPGPU_NUM_CORES

/*
 * Fixed-point format: Q10
 *
 * 1.0 = 1024
 * 2.0 = 2048
 * 4.0 = 4096
 */
#define FP_SHIFT 10
#define FP_ONE (1 << FP_SHIFT)

#define MAX_ITER 64
#define ESCAPE_RADIUS2_Q (4 << FP_SHIFT)

/*
 * Default Mandelbrot viewport:
 * center = (-0.75, 0.0)
 * scale  = 3.0
 */
#define DEFAULT_CENTER_RE_Q (-768)   /* -0.75 * 1024 */
#define DEFAULT_CENTER_IM_Q (0)
#define DEFAULT_SCALE_Q     (3072)   /*  3.00 * 1024 */

/*
 * For x86 CSV generation only.
 */
#define DEFAULT_FRAMES 120
#define DEFAULT_ZOOM_NUM 97
#define DEFAULT_ZOOM_DEN 100

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
    int pixel_step_q = scale_q >> LOG2_WIDTH;

    int cx = center_re_q + (((int)px - (WIDTH >> 1)) * pixel_step_q);
    int cy = center_im_q + (((int)py - (HEIGHT >> 1)) * pixel_step_q);

    int zr = 0;
    int zi = 0;

    int escaped = 0;
    int escape_iter = MAX_ITER;

    for (int iter = 0; iter < MAX_ITER; iter++) {
        int zr2 = fixed_mul(zr, zr);
        int zi2 = fixed_mul(zi, zi);
        int mag2 = zr2 + zi2;

        /*
         * This should compile to a compare instruction, not a branch.
         * Check the generated RISC-V assembly to verify.
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
         * Freeze z after escape so values do not grow and overflow.
         */
        int update_mask = -(escaped ^ 1);

        zr = select_int(zr, zr_next, update_mask);
        zi = select_int(zi, zi_next, update_mask);
    }

    return escape_iter;
}

#ifdef __riscv

__attribute__((noinline, used, patchable_function_entry(1, 0)))
void kernel_main(void)
{
    unsigned int tid = gpgpu_thread_id();

    /*
     * Args:
     *   GPGPU_ARGS[0] = row index, 0..63
     *   GPGPU_ARGS[1] = center_re_q
     *   GPGPU_ARGS[2] = center_im_q
     *   GPGPU_ARGS[3] = scale_q
     */
    unsigned int row = (unsigned int)GPGPU_ARGS[0];
    int center_re_q = GPGPU_ARGS[1];
    int center_im_q = GPGPU_ARGS[2];
    int scale_q = GPGPU_ARGS[3];

    /*
     * 32 cores, 64 pixels per row.
     * Each core computes two pixels.
     */
    unsigned int x0 = tid;
    unsigned int x1 = tid + CORES;

    int iter0 = mandel_pixel(x0, row, center_re_q, center_im_q, scale_q);
    int iter1 = mandel_pixel(x1, row, center_re_q, center_im_q, scale_q);

    /*
     * Output ABI:
     *   GPGPU_OUTPUT[0..63] = iteration counts for the selected row.
     */
    GPGPU_OUTPUT[x0] = iter0;
    GPGPU_OUTPUT[x1] = iter1;

    return;
}

GPGPU_START(kernel_main)

#else

#include <stdio.h>
#include <stdlib.h>

static void print_csv_header(void)
{
    printf("frame,row");

    for (int x = 0; x < WIDTH; x++) {
        printf(",p%d", x);
    }

    printf("\n");
}

static void print_mandelbrot_row(
    int frame,
    int row,
    int center_re_q,
    int center_im_q,
    int scale_q
)
{
    printf("%d,%d", frame, row);

    for (unsigned int x = 0; x < WIDTH; x++) {
        int iter = mandel_pixel(x, (unsigned int)row, center_re_q, center_im_q, scale_q);
        printf(",%d", iter);
    }

    printf("\n");
}

int main(int argc, char **argv)
{
    int frames = DEFAULT_FRAMES;
    int center_re_q = DEFAULT_CENTER_RE_Q;
    int center_im_q = DEFAULT_CENTER_IM_Q;
    int scale_q = DEFAULT_SCALE_Q;

    /*
     * Optional x86 arguments:
     *
     *   ./mandelbrot_x86 frames center_re_q center_im_q scale_q
     *
     * Example:
     *   ./mandelbrot_x86 120 -768 0 3072 > data.csv
     */
    if (argc >= 2) {
        frames = atoi(argv[1]);
    }

    if (argc >= 5) {
        center_re_q = atoi(argv[2]);
        center_im_q = atoi(argv[3]);
        scale_q = atoi(argv[4]);
    }

    if (frames < 1) {
        frames = 1;
    }

    print_csv_header();

    for (int frame = 0; frame < frames; frame++) {
        for (int row = 0; row < HEIGHT; row++) {
            print_mandelbrot_row(
                frame,
                row,
                center_re_q,
                center_im_q,
                scale_q
            );
        }

        /*
         * Zoom in for the next frame.
         *
         * This division is x86-only host/reference code.
         * The RISC-V kernel receives the already-computed scale_q.
         */
        scale_q = (scale_q * DEFAULT_ZOOM_NUM) / DEFAULT_ZOOM_DEN;

        if (scale_q < 1) {
            scale_q = 1;
        }
    }

    return 0;
}

#endif