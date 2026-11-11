#include "../gpgpu_runtime.h"

#define CORES GPGPU_NUM_CORES

/*
 * DDR read test: copies `count` words from the texture region (DDR, read-only
 * for the GPU) to a framebuffer (DDR, write-only). Lane t copies words
 * t, t + step, t + 2 * step, ..., so with step = CORES every load reads CORES
 * consecutive words: one DDR read burst per load and one write burst per
 * store.
 *
 * On the board the host fills the texture with a picture (`texfill`), the
 * kernel copies it, and the host compares the framebuffer with the texture
 * word by word (`texcheck`); fpga.py runs the three steps.
 */
static inline __attribute__((always_inline)) void
copy_words(volatile unsigned int *dst, const volatile unsigned int *src,
           unsigned int count, unsigned int first, unsigned int step)
{
    for (unsigned int i = first; i < count; i += step)
        dst[i] = src[i];
}

#ifdef __riscv

void main(void)
{
    /*
     * Args:
     *   GPGPU_ARGS[0] = destination, byte address (GPGPU_FB0_BASE or GPGPU_FB1_BASE)
     *   GPGPU_ARGS[1] = source, byte address in the texture region (GPGPU_TEX_BASE + offset)
     *   GPGPU_ARGS[2] = words to copy, a multiple of CORES (branches follow lane 0)
     */
    volatile unsigned int *dst = (volatile unsigned int *)(uintptr_t)GPGPU_ARGS[0];
    const volatile unsigned int *src = (const volatile unsigned int *)(uintptr_t)GPGPU_ARGS[1];
    unsigned int count = (unsigned int)GPGPU_ARGS[2];

    copy_words(dst, src, count, gpgpu_thread_id(), CORES);
}

GPGPU_START(main)

#else

#include <stdio.h>
#include <stdlib.h>

/* ./texcopy_x86 < in.ppm > out.ppm: the expected framebuffer is the source
 * picture, copied by the same loop as the kernel. */
int main(void)
{
    unsigned int width, height, maxval;

    if (scanf("P6 %u %u %u", &width, &height, &maxval) != 3 || maxval != 255 ||
        getchar() == EOF) {
        fprintf(stderr, "usage: texcopy_x86 < in.ppm (binary P6, maxval 255) > out.ppm\n");
        return 1;
    }

    unsigned int count = width * height;
    unsigned int *src = malloc(count * sizeof(*src));
    unsigned int *dst = malloc(count * sizeof(*dst));

    if (src == NULL || dst == NULL)
        return 1;

    for (unsigned int i = 0; i < count; i++) {
        int r = getchar(), g = getchar(), b = getchar();

        if (b == EOF) {
            fprintf(stderr, "texcopy_x86: picture ends early\n");
            return 1;
        }
        src[i] = ((unsigned int)r << 16) | ((unsigned int)g << 8) | (unsigned int)b;
    }

    copy_words(dst, src, count, 0, 1);

    printf("P6\n%u %u\n255\n", width, height);
    for (unsigned int i = 0; i < count; i++) {
        putchar((dst[i] >> 16) & 0xFF);
        putchar((dst[i] >> 8) & 0xFF);
        putchar(dst[i] & 0xFF);
    }

    free(src);
    free(dst);
    return 0;
}

#endif
