#include "../gpgpu_runtime.h"

#define CORES GPGPU_NUM_CORES

/* XRGB8888: 0x00RRGGBB. GREEN is RED >> 8 and BLUE is RED >> 16. */
#define RED        0x00FF0000u

/*
 * Three vertical bars: red, green, blue. Branches follow lane 0, so each lane
 * computes its color without an if: bar = 0, 1 or 2 shifts RED down to GREEN
 * or BLUE. (A mask select compiles back into a branch at -O2.) Comparing 3x
 * against the width avoids width / 3: the GPU runs only MUL of the M
 * extension, and GCC turns the division into MULHU.
 */
static inline unsigned int bar_color(unsigned int x, unsigned int width)
{
    unsigned int bar = (3 * x >= width) + (3 * x >= 2 * width);

    return RED >> (8 * bar);
}

#ifdef __riscv

void main(void)
{
    unsigned int tid = gpgpu_thread_id();

    /*
     * Args:
     *   GPGPU_ARGS[0] = framebuffer base, byte address (GPGPU_FB0_BASE or GPGPU_FB1_BASE)
     *   GPGPU_ARGS[1] = width in pixels, a multiple of CORES
     *   GPGPU_ARGS[2] = height in pixels
     */
    volatile unsigned int *fb = (volatile unsigned int *)(uintptr_t)GPGPU_ARGS[0];
    unsigned int width = (unsigned int)GPGPU_ARGS[1];
    unsigned int height = (unsigned int)GPGPU_ARGS[2];

    /* The loops are the same for every lane. Each store writes CORES
     * consecutive pixels, one DDR burst. */
    for (unsigned int y = 0; y < height; y++) {
        volatile unsigned int *row = fb + y * width;

        for (unsigned int x0 = 0; x0 < width; x0 += CORES) {
            unsigned int x = x0 + tid;

            row[x] = bar_color(x, width);
        }
    }

    return;
}

GPGPU_START(main)

#else

#include <stdio.h>
#include <stdlib.h>

/* ./pixels_x86 width height > pixels.ppm writes the expected image. */
int main(int argc, char **argv)
{
    if (argc != 3) {
        fprintf(stderr, "usage: %s width height\n", argv[0]);
        return 1;
    }

    unsigned int width = (unsigned int)strtoul(argv[1], NULL, 0);
    unsigned int height = (unsigned int)strtoul(argv[2], NULL, 0);

    printf("P6\n%u %u\n255\n", width, height);

    for (unsigned int y = 0; y < height; y++) {
        for (unsigned int x = 0; x < width; x++) {
            unsigned int color = bar_color(x, width);

            putchar((color >> 16) & 0xFF);
            putchar((color >> 8) & 0xFF);
            putchar(color & 0xFF);
        }
    }

    return 0;
}

#endif
