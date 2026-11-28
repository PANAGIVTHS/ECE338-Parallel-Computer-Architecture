#ifndef TRIANGLE_H
#define TRIANGLE_H

/*
 * What the kernel (triangle.c) and the host program (host.c) share: the
 * triangle, its edge functions and the inside test.
 *
 * Pixel (x, y) is inside when all three edge functions are >= 0 after the
 * vertices are put in one winding. The top-left rule decides pixels exactly
 * on an edge, so triangles sharing an edge never draw a pixel twice or leave
 * a gap. Vertices are signed integer pixels, |v| < 8192.
 */

#include "gpgpu_types.h"

#define INLINE static inline __attribute__((always_inline))

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

#endif /* TRIANGLE_H */
