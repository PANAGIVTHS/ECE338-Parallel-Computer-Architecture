#include "../gpgpu_runtime.h"
#include "../gpgpu_blit.h"

/*
 * Show an 8-bit indexed picture on the display: the whole kernel is
 * gpgpu_blit(). A host program that draws its own picture (a game without a
 * kernel of its own) loads this one and runs it once per frame.
 *
 * Args:
 *   GPGPU_ARGS[0] = byte address of a gpgpu_blit_t in GMEM
 *
 * Natively, `./blit_x86 > blit.ppm` scales a 64x40 test picture to 192x144
 * (3x across, 3.6x down, as a 320x200 game goes to 960x720) through every
 * lane in turn, and exits non-zero if a pixel is not the one nearest-neighbour
 * scaling gives.
 */

#ifdef __riscv

/* Not static: GPGPU_START calls it by name from assembly. */
void kernel_main(void)
{
    gpgpu_blit(gpgpu_thread_id(), (const volatile gpgpu_blit_t *)(uintptr_t)GPGPU_ARGS[0]);
}

GPGPU_START(kernel_main)

#elif defined(GPGPU_NATIVE_LIB)

/* The kernel on every lane, for a host that has no GPU. No lane reads what
 * another writes, so the lanes run one after the other. */
void gpgpu_kernel_run(const uint32_t *args)
{
    for (unsigned int tid = 0; tid < GPGPU_NUM_CORES; tid++)
        gpgpu_blit(tid, (const volatile gpgpu_blit_t *)(uintptr_t)args[0]);
}

#else

#include <stdio.h>
#include "../gpgpu_native.h"

#define CORES    GPGPU_NUM_CORES
#define SRC_W    64u
#define SRC_H    40u
#define SCALE_X  3u
#define DST_W    (SRC_W * SCALE_X)
#define DST_H    144u /* 3.6 x SRC_H: a ratio that is not a whole number */

int main(void)
{
    /* The output is whole chunks of CORES pixels: round the width down. */
    uint32_t chunks = DST_W / CORES;
    uint32_t width = chunks * CORES;
    uint8_t *src = gpgpu_native_alloc(SRC_W * SRC_H);
    uint32_t *palette = gpgpu_native_alloc(256 * sizeof(uint32_t));
    uint32_t *dst = gpgpu_native_alloc(DST_W * DST_H * sizeof(uint32_t));
    gpgpu_blit_t *blit = gpgpu_native_alloc(sizeof(*blit));

    if (chunks == 0) {
        fprintf(stderr, "blit: the test picture is narrower than %u lanes\n", (unsigned)CORES);
        return 1;
    }
    for (uint32_t i = 0; i < 256; i++)
        palette[i] = (i << 16) | ((255u - i) << 8) | ((i * 7u) & 0xFFu);
    for (uint32_t y = 0; y < SRC_H; y++)
        for (uint32_t x = 0; x < SRC_W; x++)
            src[y * SRC_W + x] = (uint8_t)(x * 4u + y * 3u);

    *blit = (gpgpu_blit_t){
        .src = gpgpu_native_address(src), .src_stride = SRC_W,
        .palette = gpgpu_native_address(palette),
        .dst = gpgpu_native_address(dst), .dst_stride = DST_W * 4u,
        .dst_chunks = chunks, .dst_rows = DST_H,
        .x_step = GPGPU_BLIT_STEP(SRC_W, DST_W), .y_step = GPGPU_BLIT_STEP(SRC_H, DST_H),
    };
    for (unsigned int tid = 0; tid < CORES; tid++)
        gpgpu_blit(tid, blit);

    unsigned int wrong = 0;

    printf("P6\n%u %u\n255\n", width, DST_H);
    for (uint32_t y = 0; y < DST_H; y++) {
        for (uint32_t x = 0; x < width; x++) {
            uint32_t color = dst[y * DST_W + x];
            uint32_t expected = palette[src[(y * SRC_H / DST_H) * SRC_W + x * SRC_W / DST_W]];

            wrong += color != expected;
            putchar((int)((color >> 16) & 0xFF));
            putchar((int)((color >> 8) & 0xFF));
            putchar((int)(color & 0xFF));
        }
    }
    if (wrong != 0)
        fprintf(stderr, "blit: %u pixels differ from nearest-neighbour scaling\n", wrong);
    return wrong != 0;
}

#endif
