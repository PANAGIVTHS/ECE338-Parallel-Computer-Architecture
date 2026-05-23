#define CORES 32
#define WIDTH 32
#define HEIGHT 16
#define PIXELS (WIDTH * HEIGHT)
#define MAX_ITERS 32

#define FP_SHIFT 10
#define FP_ONE (1 << FP_SHIFT)
#define X_MIN (-2 * FP_ONE)
#define Y_MIN (-1 * FP_ONE)
#define X_STEP ((3 * FP_ONE) / (WIDTH - 1))
#define Y_STEP ((2 * FP_ONE) / (HEIGHT - 1))
#define ESCAPE_RADIUS_SQ (4 * FP_ONE)

int mandelbrot_nodiv_output[PIXELS] = {0};

static inline __attribute__((always_inline))
int select_int(int old_value, int new_value, int do_update)
{
    int mask = -do_update;
    return (old_value & ~mask) | (new_value & mask);
}

static inline __attribute__((always_inline))
int mandelbrot_pixel_nodiv(int pixel_x, int pixel_y)
{
    int c_re = X_MIN + pixel_x * X_STEP;
    int c_im = Y_MIN + pixel_y * Y_STEP;
    int z_re = 0;
    int z_im = 0;
    int iter_count = 0;
    int active = 1;

    /*
     * This loop intentionally runs exactly MAX_ITERS iterations for every
     * core/pixel. There is no data-dependent break, so all 32 GPU lanes follow
     * the same control-flow path on the shared-PC SMX.
     */
    for (int iter = 0; iter < MAX_ITERS; iter++) {
        int z_re_sq = (z_re * z_re) >> FP_SHIFT;
        int z_im_sq = (z_im * z_im) >> FP_SHIFT;
        int magnitude_sq = z_re_sq + z_im_sq;

        /* still_inside is 1 while |z|^2 <= 4. Avoid if/break divergence. */
        int escaped = ESCAPE_RADIUS_SQ < magnitude_sq;
        int still_inside = escaped ^ 1;
        int do_update = active & still_inside;

        int z_re_z_im = (z_re * z_im) >> (FP_SHIFT - 1);
        int next_z_im = z_re_z_im + c_im;
        int next_z_re = z_re_sq - z_im_sq + c_re;

        iter_count += do_update;
        z_re = select_int(z_re, next_z_re, do_update);
        z_im = select_int(z_im, next_z_im, do_update);
        active = do_update;
    }

    return iter_count;
}

#ifdef __riscv

__attribute__((naked,noreturn))
void _start()
{
    int threadIdx_x;

    __asm__ volatile("mv %0, x31" : "=r"(threadIdx_x));

    /*
     * WIDTH is 32, matching CORES, so each GPU thread owns one column.
     * The inner Mandelbrot iteration loop is fixed-length and branchless with
     * respect to pixel escape, avoiding unsupported warp divergence.
     */
    for (int y = 0; y < HEIGHT; y++) {
        int idx = y * WIDTH + threadIdx_x;
        mandelbrot_nodiv_output[idx] = mandelbrot_pixel_nodiv(threadIdx_x, y);
    }

    __asm__ volatile("jalr x0, 0(x1)");
    __builtin_unreachable();
}

#else

#include <stdio.h>

static char shade_for_iter(int iter)
{
    const char shades[] = " .:-=+*#%@";
    int shade_count = (int)(sizeof(shades) - 1);

    if (iter >= MAX_ITERS)
        return '@';

    return shades[(iter * (shade_count - 1)) / MAX_ITERS];
}

int main()
{
    for (int y = 0; y < HEIGHT; y++) {
        for (int x = 0; x < WIDTH; x++) {
            mandelbrot_nodiv_output[y * WIDTH + x] = mandelbrot_pixel_nodiv(x, y);
        }
    }

    printf("Non-divergent Mandelbrot set (%dx%d, max_iters=%d)\n", WIDTH, HEIGHT, MAX_ITERS);
    for (int y = 0; y < HEIGHT; y++) {
        for (int x = 0; x < WIDTH; x++) {
            putchar(shade_for_iter(mandelbrot_nodiv_output[y * WIDTH + x]));
        }
        putchar('\n');
    }

    printf("\nIteration counts:\n");
    for (int y = 0; y < HEIGHT; y++) {
        for (int x = 0; x < WIDTH; x++) {
            printf("%2d ", mandelbrot_nodiv_output[y * WIDTH + x]);
        }
        putchar('\n');
    }

    return 0;
}

#endif
