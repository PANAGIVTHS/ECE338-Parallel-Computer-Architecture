#include "../gpgpu_runtime.h"
#include "mandelbrot.h"

#define CORES GPGPU_NUM_CORES

#ifdef __riscv

#include <stdint.h>

#define MANDEL_ROW_SHIFT 26
#define MANDEL_SCALE_MASK ((1u << MANDEL_ROW_SHIFT) - 1u)

void kernel_main(void)
{
    unsigned int tid = gpgpu_thread_id();

    /*
     * Args:
     *   GPGPU_ARGS[0] = output row pointer, byte address
     *   GPGPU_ARGS[1] = packed row + scale_q
     *                    bits [31:26] = row, 0..63
     *                    bits [25:0]  = scale_q
     *   GPGPU_ARGS[2] = center_re_q
     *   GPGPU_ARGS[3] = center_im_q
     */
    volatile int *output = (volatile int *)(uintptr_t)GPGPU_ARGS[0];

    unsigned int packed = (unsigned int)GPGPU_ARGS[1];

    unsigned int row = packed >> MANDEL_ROW_SHIFT;
    int scale_q = (int)(packed & MANDEL_SCALE_MASK);

    int center_re_q = GPGPU_ARGS[2];
    int center_im_q = GPGPU_ARGS[3];

    /*
     * 32 cores, 64 pixels per row.
     * Each core computes two pixels.
     */
    unsigned int x0 = tid;
    unsigned int x1 = tid + CORES;

    int iter0 = mandel_pixel(x0, row, center_re_q, center_im_q, scale_q);
    int iter1 = mandel_pixel(x1, row, center_re_q, center_im_q, scale_q);

    /*
     * Output row:
     *   output[0..63] = iteration counts for the selected row.
     */
    output[x0] = iter0;
    output[x1] = iter1;

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
     *   ./mandelbrot_x86 160 -6092 1080 24576 > data.csv
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

        if (scale_q < 64) {
            /*
             * Below 64, pixel_step_q = scale_q >> 6 becomes zero, so every
             * pixel maps to the same complex coordinate and the image stops
             * changing.
             */
            scale_q = 64;
        }
    }

    return 0;
}

#endif