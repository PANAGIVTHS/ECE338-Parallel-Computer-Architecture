/*
 * triangle: a flat-shaded triangle rasterizer with edge functions
 * (triangle.h), without divergence.
 *
 * Block y of the grid draws row y of a width x height picture at fb: launch
 * it over gpgpu_dim3(1, height). Every lane runs the same loops and takes the
 * same branches: loop bounds, the winding swap and the tail chunk depend only
 * on the parameters, never on the lane. The per-pixel "inside the triangle?"
 * decision is a mask (0 or ~0) that selects between the triangle and the
 * background color, so every lane stores every time. Each store writes 32
 * consecutive pixels, one DDR burst.
 *
 * Parameters: the framebuffer, the picture's width (at least 32, any value)
 * and the triangle, which is too large for parameter words: tri points to a
 * tri_params_t in GMEM (triangle_params).
 */
#include "gpgpu_device.h"
#include "triangle.h"

#define CORES ((int)GPGPU_NUM_CORES)

GPGPU_DEVICE tri_params_t triangle_params;

GPGPU_GLOBAL void triangle(unsigned int *fb, int width, const tri_params_t *tri)
{
    int tid = (int)gpgpu_thread_idx();
    int y = (int)gpgpu_block_idx_y();
    edge_t a, b, c;
    unsigned int fg, bg = tri->background;

    triangle_setup(*tri, &a, &b, &c, &fg);

    /* This lane's edge values at (tid, y), and their step per chunk. */
    int row_a = a.value + tid * a.step_x + y * a.step_y;
    int row_b = b.value + tid * b.step_x + y * b.step_y;
    int row_c = c.value + tid * c.step_x + y * c.step_y;
    int chunk_a = CORES * a.step_x;
    int chunk_b = CORES * b.step_x;
    int chunk_c = CORES * c.step_x;

    /* Width not a multiple of CORES: the row ends with one more chunk at
     * x = width - CORES, overlapping the last full one. The overlapped pixels
     * get the same color again and no two lanes share a word. */
    int full = 0;                      /* pixels in full chunks */
    while (full + CORES <= width) {    /* no width % CORES: the GPU has no divider */
        full += CORES;
        __asm__("" : "+r"(full));      /* keep GCC from folding it back into a division */
    }
    int tail = width - CORES;          /* x of the tail chunk */
    unsigned int diff = fg ^ bg;

    volatile unsigned int *row = fb + y * width + tid;
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
        row[tail] = bg ^ (diff & inside_mask(row_a + tail * a.step_x, row_b + tail * b.step_x, row_c + tail * c.step_x));
}
