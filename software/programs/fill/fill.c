#include "../gpgpu_runtime.h"

#define CORES GPGPU_NUM_CORES

/*
 * A one-pixel checkerboard of two colors: c0 where x + y is even, c1 where
 * it is odd. c0 == c1 fills the framebuffer with one color; black and white
 * give the most TMDS transitions per pixel. Branches follow lane 0, so the
 * parity selects the color by a multiply (0 or 1) instead of an if.
 */
static inline unsigned int fill_color(unsigned int x, unsigned int y,
                                      unsigned int c0, unsigned int c1)
{
    unsigned int odd = (x + y) & 1u;

    /* Hides that odd is 0 or 1, so GCC keeps the multiply instead of
     * turning the select back into a branch. */
    __asm__ volatile("" : "+r"(odd));
    return c0 ^ ((c0 ^ c1) * odd);
}

#ifdef __riscv

void main(void)
{
    unsigned int tid = gpgpu_thread_id();

    /*
     * Args:
     *   GPGPU_ARGS[0] = framebuffer base, byte address (GPGPU_FB0_BASE or GPGPU_FB1_BASE)
     *   GPGPU_ARGS[1] = width in pixels (a multiple of CORES) | height << 16
     *   GPGPU_ARGS[2] = c0, 0x00RRGGBB
     *   GPGPU_ARGS[3] = c1, 0x00RRGGBB
     */
    volatile unsigned int *fb = (volatile unsigned int *)(uintptr_t)GPGPU_ARGS[0];
    unsigned int width = (unsigned int)GPGPU_ARGS[1] & 0xFFFFu;
    unsigned int height = (unsigned int)GPGPU_ARGS[1] >> 16;
    unsigned int c0 = (unsigned int)GPGPU_ARGS[2];
    unsigned int c1 = (unsigned int)GPGPU_ARGS[3];

    /* Each store writes CORES consecutive pixels, one DDR burst. */
    for (unsigned int y = 0; y < height; y++) {
        volatile unsigned int *row = fb + y * width;

        for (unsigned int x0 = 0; x0 < width; x0 += CORES) {
            unsigned int x = x0 + tid;

            row[x] = fill_color(x, y, c0, c1);
        }
    }

    return;
}

GPGPU_START(main)

#else

#include <stdio.h>
#include <stdlib.h>

/* ./fill_x86 width height c0 c1 > fill.ppm writes the expected image. */
int main(int argc, char **argv)
{
    if (argc != 5) {
        fprintf(stderr, "usage: %s width height c0 c1\n", argv[0]);
        return 1;
    }

    unsigned int width = (unsigned int)strtoul(argv[1], NULL, 0);
    unsigned int height = (unsigned int)strtoul(argv[2], NULL, 0);
    unsigned int c0 = (unsigned int)strtoul(argv[3], NULL, 0);
    unsigned int c1 = (unsigned int)strtoul(argv[4], NULL, 0);

    printf("P6\n%u %u\n255\n", width, height);

    for (unsigned int y = 0; y < height; y++) {
        for (unsigned int x = 0; x < width; x++) {
            unsigned int color = fill_color(x, y, c0, c1);

            putchar((color >> 16) & 0xFF);
            putchar((color >> 8) & 0xFF);
            putchar(color & 0xFF);
        }
    }

    return 0;
}

#endif
