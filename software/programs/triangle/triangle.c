#include "../gpgpu_runtime.h"

#define CORES ((int)GPGPU_NUM_CORES)

/* Every helper must be inlined: a call needs AUIPC, which the core does not
 * decode, and a function's RET (jalr x0, 0(x1)) would end the kernel. */
#define INLINE static inline __attribute__((always_inline))

/*
 * Flat-shaded triangle rasterizer with edge functions, no divergence.
 *
 * Every lane runs the same loops and takes the same branches: loop bounds,
 * the winding swap and the tail-chunk test depend only on the arguments,
 * never on the lane id. The per-pixel "inside the triangle?" decision is a
 * mask (0 or ~0) that selects between the triangle and background colors, so
 * every lane stores every time. Each store writes CORES consecutive pixels,
 * one DDR burst.
 *
 * Args (host DMEM word index in brackets):
 *   GPGPU_ARGS[0] [16] framebuffer byte address (GPGPU_FB0_BASE or GPGPU_FB1_BASE)
 *   GPGPU_ARGS[1] [17] width in pixels, >= CORES (any value, not only multiples)
 *   GPGPU_ARGS[2] [18] height in pixels
 *   GPGPU_ARGS[3] [19] unused
 *   TRI[0..5]     [20..25] x0 y0 x1 y1 x2 y2, signed integer pixels, |v| < 8192
 *   TRI[6]        [26] triangle color 0x00RRGGBB
 *   TRI[7]        [27] background color 0x00RRGGBB
 *
 * Pixel (x, y) is inside when all three edge functions are >= 0 after the
 * vertices are put in one winding. The top-left rule decides pixels exactly
 * on an edge, so triangles sharing an edge never draw a pixel twice or leave
 * a gap.
 */

typedef struct {
    int x0, y0, x1, y1, x2, y2;
    unsigned int color;
    unsigned int background;
} tri_params_t;

/* One edge a->b. value(x, y) = step_y * (y - ay) + step_x * (x - ax). */
typedef struct {
    int step_x; /* change per pixel to the right: ay - by */
    int step_y; /* change per row down: bx - ax */
    int value;  /* at (0, 0), top-left bias included */
} edge_t;

INLINE edge_t edge_setup(int ax, int ay, int bx, int by)
{
    edge_t e;

    e.step_x = ay - by;
    e.step_y = bx - ax;
    e.value = -e.step_y * ay - e.step_x * ax;
    /* Top-left rule: a pixel on a left edge (inside lies to the right) or a
     * top edge (horizontal, inside lies below) belongs to the triangle;
     * on any other edge it needs value > 0, i.e. value - 1 >= 0. */
    int top_left = (e.step_x > 0) | ((e.step_x == 0) & (e.step_y > 0));
    e.value -= 1 - top_left;
    return e;
}

/* ~0 when every value is >= 0, else 0. The empty asm hides the mask from the
 * optimizer, so GCC cannot turn the select below back into a branch. */
INLINE unsigned int inside_mask(int e0, int e1, int e2)
{
    unsigned int m = ~(unsigned int)((e0 | e1 | e2) >> 31);

    __asm__("" : "+r"(m));
    return m;
}

INLINE unsigned int shade(unsigned int mask, unsigned int fg, unsigned int bg)
{
    return bg ^ ((fg ^ bg) & mask);
}

/* Put the vertices in the winding where the area is positive. A degenerate
 * triangle (area 0) draws nothing: its color becomes the background. */
INLINE void triangle_setup(tri_params_t t, edge_t *e01, edge_t *e12, edge_t *e20,
                                  unsigned int *fg)
{
    int area = (t.x1 - t.x0) * (t.y2 - t.y0) - (t.y1 - t.y0) * (t.x2 - t.x0);

    if (area < 0) { /* the same for every lane */
        int sx = t.x1, sy = t.y1;
        t.x1 = t.x2; t.y1 = t.y2;
        t.x2 = sx;   t.y2 = sy;
    }
    *e01 = edge_setup(t.x0, t.y0, t.x1, t.y1);
    *e12 = edge_setup(t.x1, t.y1, t.x2, t.y2);
    *e20 = edge_setup(t.x2, t.y2, t.x0, t.y0);
    *fg = area == 0 ? t.background : t.color;
}

#ifdef __riscv

#define TRI ((volatile const int *)(GPGPU_ARGS + 4))

void main(void)
{
    unsigned int tid = gpgpu_thread_id();
    volatile unsigned int *fb = (volatile unsigned int *)(uintptr_t)GPGPU_ARGS[0];
    int width = GPGPU_ARGS[1];
    int height = GPGPU_ARGS[2];

    tri_params_t t = {
        TRI[0], TRI[1], TRI[2], TRI[3], TRI[4], TRI[5],
        (unsigned int)TRI[6], (unsigned int)TRI[7],
    };
    edge_t a, b, c;
    unsigned int fg, bg = t.background;
    triangle_setup(t, &a, &b, &c, &fg);

    /* This lane's edge values at (tid, 0), and their step per chunk. */
    int row_a = a.value + (int)tid * a.step_x;
    int row_b = b.value + (int)tid * b.step_x;
    int row_c = c.value + (int)tid * c.step_x;
    int chunk_a = CORES * a.step_x;
    int chunk_b = CORES * b.step_x;
    int chunk_c = CORES * c.step_x;

    /* Width not a multiple of CORES: each row ends with one more chunk at
     * x = width - CORES, overlapping the last full one. The overlapped pixels
     * get the same color again and no two lanes share a word. That chunk is
     * at the same place in every row, so its edge offsets are constants. */
    int full = 0;                      /* pixels in full chunks */
    while (full + CORES <= width) {    /* no width % CORES: the GPU has no divider */
        full += CORES;
        __asm__("" : "+r"(full));      /* keep GCC from folding it back into a division */
    }
    int tail = width - CORES;          /* x of the tail chunk */
    int tail_a = tail * a.step_x;
    int tail_b = tail * b.step_x;
    int tail_c = tail * c.step_x;
    unsigned int diff = fg ^ bg;

    volatile unsigned int *row = fb + tid;
    volatile unsigned int *last = row + height * width;

    for (; row != last; row += width) {
        volatile unsigned int *p = row;
        volatile unsigned int *end = row + full;
        int ea = row_a, eb = row_b, ec = row_c;

        for (; p != end; p += CORES) {
            *p = bg ^ (diff & inside_mask(ea, eb, ec));
            ea += chunk_a;
            eb += chunk_b;
            ec += chunk_c;
        }
        if (full != width) /* the same for every lane */
            row[tail] = bg ^ (diff & inside_mask(row_a + tail_a, row_b + tail_b, row_c + tail_c));

        row_a += a.step_y;
        row_b += b.step_y;
        row_c += c.step_y;
    }

    return;
}

GPGPU_START(main)

#else

#include <stdio.h>
#include <stdlib.h>

/* Reference: every pixel evaluated directly, no incremental stepping.
 * ./triangle_x86 width height x0 y0 x1 y1 x2 y2 color background > tri.ppm */
int main(int argc, char **argv)
{
    if (argc != 11) {
        fprintf(stderr, "usage: %s width height x0 y0 x1 y1 x2 y2 color background\n", argv[0]);
        return 1;
    }

    int width = (int)strtol(argv[1], NULL, 0);
    int height = (int)strtol(argv[2], NULL, 0);
    tri_params_t t = {
        (int)strtol(argv[3], NULL, 0), (int)strtol(argv[4], NULL, 0),
        (int)strtol(argv[5], NULL, 0), (int)strtol(argv[6], NULL, 0),
        (int)strtol(argv[7], NULL, 0), (int)strtol(argv[8], NULL, 0),
        (unsigned int)strtoul(argv[9], NULL, 0), (unsigned int)strtoul(argv[10], NULL, 0),
    };
    edge_t a, b, c;
    unsigned int fg;
    triangle_setup(t, &a, &b, &c, &fg);

    printf("P6\n%d %d\n255\n", width, height);
    for (int y = 0; y < height; y++) {
        for (int x = 0; x < width; x++) {
            int ea = a.value + a.step_x * x + a.step_y * y;
            int eb = b.value + b.step_x * x + b.step_y * y;
            int ec = c.value + c.step_x * x + c.step_y * y;
            unsigned int color = shade(inside_mask(ea, eb, ec), fg, t.background);

            putchar((color >> 16) & 0xFF);
            putchar((color >> 8) & 0xFF);
            putchar(color & 0xFF);
        }
    }
    return 0;
}

#endif