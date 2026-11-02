#include "../gpgpu_runtime.h"

#define CORES GPGPU_NUM_CORES

/*
 * An animated test pattern for measuring frame rate: red rings ripple out of
 * the centre, green and blue XOR patterns scroll across it.
 *
 * Lanes branch with lane 0, so the pixel color is computed straight through
 * (no if, no ?:) and the loops are the same for every lane. It uses only
 * add, sub, xor, and, shifts and MUL: the GPU has no divider and returns the
 * low product for every other M-extension instruction.
 */
static inline unsigned int ripple_color(unsigned int x, unsigned int y,
                                        unsigned int width, unsigned int height,
                                        unsigned int frame)
{
    int dx = (int)x - (int)(width >> 1);
    int dy = (int)y - (int)(height >> 1);
    unsigned int distance2 = (unsigned int)(dx * dx + dy * dy);

    unsigned int red = ((distance2 >> 8) - 4u * frame) & 0xFFu;
    unsigned int green = ((x + frame) ^ y) & 0xFFu;
    unsigned int blue = (x ^ (y + 2u * frame)) & 0xFFu;

    return (red << 16) | (green << 8) | blue;  /* 0x00RRGGBB */
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
     *   GPGPU_ARGS[3] = frame number; the kernel advances it, so each run
     *                   draws the next frame with no host writes in between
     */
    volatile unsigned int *fb = (volatile unsigned int *)(uintptr_t)GPGPU_ARGS[0];
    unsigned int width = (unsigned int)GPGPU_ARGS[1];
    unsigned int height = (unsigned int)GPGPU_ARGS[2];
    unsigned int frame = (unsigned int)GPGPU_ARGS[3];

    /* Each store writes CORES consecutive pixels, one DDR burst. */
    for (unsigned int y = 0; y < height; y++) {
        volatile unsigned int *row = fb + y * width;

        for (unsigned int x0 = 0; x0 < width; x0 += CORES) {
            unsigned int x = x0 + tid;

            row[x] = ripple_color(x, y, width, height, frame);
        }
    }

    /* Every lane stores the same value. */
    GPGPU_ARGS[3] = (int)(frame + 1u);

    return;
}

GPGPU_START(main)

#else

#include <stdio.h>
#include <stdlib.h>

/* ./ripple_x86 width height frame > ripple.ppm writes that frame. */
int main(int argc, char **argv)
{
    if (argc != 4) {
        fprintf(stderr, "usage: %s width height frame\n", argv[0]);
        return 1;
    }

    unsigned int width = (unsigned int)strtoul(argv[1], NULL, 0);
    unsigned int height = (unsigned int)strtoul(argv[2], NULL, 0);
    unsigned int frame = (unsigned int)strtoul(argv[3], NULL, 0);

    printf("P6\n%u %u\n255\n", width, height);

    for (unsigned int y = 0; y < height; y++) {
        for (unsigned int x = 0; x < width; x++) {
            unsigned int color = ripple_color(x, y, width, height, frame);

            putchar((color >> 16) & 0xFF);
            putchar((color >> 8) & 0xFF);
            putchar(color & 0xFF);
        }
    }

    return 0;
}

#endif
