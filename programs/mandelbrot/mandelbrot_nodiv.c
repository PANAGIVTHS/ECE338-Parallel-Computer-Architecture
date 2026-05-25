#define CORES 32
#define DEFAULT_WIDTH 32
#define DEFAULT_HEIGHT 16
#define DEFAULT_PIXELS (DEFAULT_WIDTH * DEFAULT_HEIGHT)
#define DEFAULT_MAX_ITERS 32

#define FP_SHIFT 10
#define FP_ONE (1 << FP_SHIFT)
#define DEFAULT_X_MIN (-2 * FP_ONE)
#define DEFAULT_Y_MIN (-1 * FP_ONE)
#define DEFAULT_X_STEP ((3 * FP_ONE) / (DEFAULT_WIDTH - 1))
#define DEFAULT_Y_STEP ((2 * FP_ONE) / (DEFAULT_HEIGHT - 1))
#define ESCAPE_RADIUS_SQ (4 * FP_ONE)

#ifdef __riscv
#include "gpu_abi.h"
#endif

enum {
    MANDEL_ARG_MAGIC = 0,
    MANDEL_ARG_WIDTH = 1,
    MANDEL_ARG_HEIGHT = 2,
    MANDEL_ARG_MAX_ITERS = 3,
    MANDEL_ARG_X_MIN = 4,
    MANDEL_ARG_Y_MIN = 5,
    MANDEL_ARG_X_STEP = 6,
    MANDEL_ARG_Y_STEP = 7,
};

#define MANDEL_ARGS_MAGIC 0x4d414e44 /* "MAND" */

struct MandelbrotArgs {
    int width;
    int height;
    int max_iters;
    int x_min;
    int y_min;
    int x_step;
    int y_step;
};

#ifndef __riscv
int mandelbrot_nodiv_output[DEFAULT_PIXELS] = {0};
#endif

static inline __attribute__((always_inline))
int select_int(int old_value, int new_value, int do_update)
{
    int mask = -do_update;
    return (old_value & ~mask) | (new_value & mask);
}

static inline __attribute__((always_inline))
void mandelbrot_default_args(struct MandelbrotArgs *args)
{
    args->width = DEFAULT_WIDTH;
    args->height = DEFAULT_HEIGHT;
    args->max_iters = DEFAULT_MAX_ITERS;
    args->x_min = DEFAULT_X_MIN;
    args->y_min = DEFAULT_Y_MIN;
    args->x_step = DEFAULT_X_STEP;
    args->y_step = DEFAULT_Y_STEP;
}

#ifdef __riscv
static inline __attribute__((always_inline))
void mandelbrot_load_args(struct MandelbrotArgs *args)
{
    volatile int *gpu_args = GPU_ARGS;

    mandelbrot_default_args(args);

    /*
     * The laptop writes this parameter block into DMEM before each kernel call.
     * If the magic word is absent, keep the compile-time defaults so the program
     * remains runnable from tests that only clear DMEM.
     */
    if (gpu_args[MANDEL_ARG_MAGIC] == MANDEL_ARGS_MAGIC) {
        args->width = gpu_args[MANDEL_ARG_WIDTH];
        args->height = gpu_args[MANDEL_ARG_HEIGHT];
        args->max_iters = gpu_args[MANDEL_ARG_MAX_ITERS];
        args->x_min = gpu_args[MANDEL_ARG_X_MIN];
        args->y_min = gpu_args[MANDEL_ARG_Y_MIN];
        args->x_step = gpu_args[MANDEL_ARG_X_STEP];
        args->y_step = gpu_args[MANDEL_ARG_Y_STEP];
    }
}
#else
static inline __attribute__((always_inline))
void mandelbrot_load_args(struct MandelbrotArgs *args)
{
    mandelbrot_default_args(args);
}
#endif

static inline __attribute__((always_inline))
int mandelbrot_pixel_nodiv(int pixel_x, int pixel_y, int max_iters,
                         int x_min, int y_min, int x_step, int y_step)
{
    int c_re = x_min + pixel_x * x_step;
    int c_im = y_min + pixel_y * y_step;
    int z_re = 0;
    int z_im = 0;
    int iter_count = 0;
    int active = 1;

    /*
     * This loop intentionally runs exactly max_iters iterations for every
     * core/pixel. There is no data-dependent break, so all 32 GPU lanes follow
     * the same control-flow path on the shared-PC SMX.
     */
    for (int iter = 0; iter < max_iters; iter++) {
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
void _start(void)
{
    int threadIdx_x;
    volatile int *gpu_args = GPU_ARGS;
    volatile int *gpu_output = GPU_OUTPUT;
    int width = DEFAULT_WIDTH;
    int height = DEFAULT_HEIGHT;
    int max_iters = DEFAULT_MAX_ITERS;
    int x_min = DEFAULT_X_MIN;
    int y_min = DEFAULT_Y_MIN;
    int x_step = DEFAULT_X_STEP;
    int y_step = DEFAULT_Y_STEP;

    __asm__ volatile("mv %0, x31" : "=r"(threadIdx_x));
    if (gpu_args[MANDEL_ARG_MAGIC] == MANDEL_ARGS_MAGIC) {
        width = gpu_args[MANDEL_ARG_WIDTH];
        height = gpu_args[MANDEL_ARG_HEIGHT];
        max_iters = gpu_args[MANDEL_ARG_MAX_ITERS];
        x_min = gpu_args[MANDEL_ARG_X_MIN];
        y_min = gpu_args[MANDEL_ARG_Y_MIN];
        x_step = gpu_args[MANDEL_ARG_X_STEP];
        y_step = gpu_args[MANDEL_ARG_Y_STEP];
    }

    /*
     * Keep this as a naked leaf kernel: no call and no stack setup.  That keeps
     * the current Mandelbrot path compatible even while general stack support is
     * still experimental on this branch.
     */
    for (int y = 0; y < height; y++) {
        int idx = y * width + threadIdx_x;
        gpu_output[idx] = mandelbrot_pixel_nodiv(threadIdx_x, y, max_iters,
                                                x_min, y_min, x_step, y_step);
    }

    __asm__ volatile("jalr x0, 0(x1)");
    __builtin_unreachable();
}

#else

#include <stdio.h>

static char shade_for_iter(int iter, int max_iters)
{
    const char shades[] = " .:-=+*#%@";
    int shade_count = (int)(sizeof(shades) - 1);

    if (iter >= max_iters)
        return '@';

    return shades[(iter * (shade_count - 1)) / max_iters];
}

int main()
{
    struct MandelbrotArgs args;
    mandelbrot_load_args(&args);

    for (int y = 0; y < args.height; y++) {
        for (int x = 0; x < args.width; x++) {
            mandelbrot_nodiv_output[y * args.width + x] = mandelbrot_pixel_nodiv(
                x, y, args.max_iters, args.x_min, args.y_min, args.x_step, args.y_step);
        }
    }

    printf("Non-divergent Mandelbrot set (%dx%d, max_iters=%d)\n", args.width, args.height, args.max_iters);
    for (int y = 0; y < args.height; y++) {
        for (int x = 0; x < args.width; x++) {
            putchar(shade_for_iter(mandelbrot_nodiv_output[y * args.width + x], args.max_iters));
        }
        putchar('\n');
    }

    printf("\nIteration counts:\n");
    for (int y = 0; y < args.height; y++) {
        for (int x = 0; x < args.width; x++) {
            printf("%2d ", mandelbrot_nodiv_output[y * args.width + x]);
        }
        putchar('\n');
    }

    return 0;
}

#endif
