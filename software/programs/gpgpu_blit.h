#ifndef GPGPU_BLIT_H
#define GPGPU_BLIT_H

/*
 * Present an 8-bit indexed picture on a framebuffer: palette lookup and
 * nearest-neighbour scaling, for any kernel that includes this file.
 *
 * It is the last step of a frame for a host program that draws a small
 * indexed picture (a game's 320x200 screen) and wants it on the 1280x720
 * display. The host fills a gpgpu_blit_t in GMEM and passes its address.
 *
 * The GPU's rules: every lane takes the same branches, so each loop count
 * below comes from the descriptor, which every lane reads from the same
 * address. There is no divider, so the scale is a 16.16 step added per pixel.
 *
 * Memory traffic per CORES output pixels of one source row:
 *   1 load of the source bytes   (at most CORES bytes: 1 or 2 DDR bursts)
 *   1 load of the palette words  (a 1 KiB table: at most 8 bursts)
 *   n stores of CORES words, one per output row showing that source row
 *     (each one burst when dst is on a CORES-pixel boundary of a row)
 * so the picture is read once, however far it is scaled up.
 */

#include <stdint.h>
#include "gpgpu_config.h"

/* Every address is a GPU byte address; `src` and `palette` must be readable
 * (GMEM), `dst` is in a framebuffer. */
typedef struct {
    uint32_t src;        /* indexed picture, one byte per pixel, rows packed */
    uint32_t src_stride; /* bytes from one source row to the next */
    uint32_t palette;    /* 256 words, 0x00RRGGBB */
    uint32_t dst;        /* framebuffer address of the first output pixel */
    uint32_t dst_stride; /* bytes from one framebuffer row to the next */
    uint32_t dst_chunks; /* output width in units of GPGPU_NUM_CORES pixels */
    uint32_t dst_rows;   /* output height in pixels */
    uint32_t x_step;     /* source pixels per output pixel, 16.16 */
    uint32_t y_step;     /* source rows per output row, 16.16 */
} gpgpu_blit_t;

/* The step for `out` output pixels to show `in` source pixels: rounded up,
 * so that an exact ratio such as 1/3 does not fall one short at every third
 * pixel. Host code only (it divides). The last output pixel must still read
 * inside the source: true while out * out < 65536 * in. */
#define GPGPU_BLIT_STEP(in, out) ((((uint32_t)(in) << 16) + (uint32_t)(out) - 1u) / (uint32_t)(out))

#define GPGPU_BLIT_INLINE static inline __attribute__((always_inline))

GPGPU_BLIT_INLINE void gpgpu_blit(unsigned int tid, const volatile gpgpu_blit_t *blit)
{
    const uint32_t cores = GPGPU_NUM_CORES;

    /* The same words in every lane: one beat each. */
    const volatile uint8_t *src = (const volatile uint8_t *)(uintptr_t)blit->src;
    uint32_t src_stride = blit->src_stride;
    const volatile uint32_t *palette = (const volatile uint32_t *)(uintptr_t)blit->palette;
    uint32_t dst_stride = blit->dst_stride;
    uint32_t chunks = blit->dst_chunks;
    uint32_t rows = blit->dst_rows;
    uint32_t x_step = blit->x_step;
    uint32_t y_step = blit->y_step;

    /* This lane's pixel of the first chunk, and its source column there. */
    volatile uint32_t *dst_row = (volatile uint32_t *)(uintptr_t)blit->dst + tid;
    uint32_t x_first = tid * x_step;
    uint32_t x_chunk = cores * x_step;

    uint32_t y_acc = 0; /* 16.16 source row of the next output row */
    uint32_t done = 0;  /* output rows drawn */

    while (done != rows) {
        uint32_t src_y = y_acc >> 16;
        uint32_t repeat = 0; /* output rows that show source row src_y */

        do {
            repeat++;
            y_acc += y_step;
        } while (done + repeat != rows && (y_acc >> 16) == src_y);

        const volatile uint8_t *line = src + src_y * src_stride;
        volatile uint32_t *out = dst_row;
        uint32_t x_acc = x_first;

        for (uint32_t chunk = 0; chunk != chunks; chunk++) {
            uint32_t color = palette[line[x_acc >> 16]];
            volatile uint32_t *pixel = out;

            for (uint32_t r = 0; r != repeat; r++) {
                *pixel = color;
                pixel = (volatile uint32_t *)((uintptr_t)pixel + dst_stride);
            }
            out += cores;
            x_acc += x_chunk;
        }

        dst_row = (volatile uint32_t *)((uintptr_t)dst_row + repeat * dst_stride);
        done += repeat;
    }
}

#endif /* GPGPU_BLIT_H */
