/*
 * sobel: the Sobel edge magnitude |gx| + |gy| of a grey image, clamped to 255,
 * and 0 on the border.
 *
 * One thread per pixel: thread i of the grid, i = block * 32 + lane, computes
 * pixel i. Launch it over gpgpu_dim3(SOBEL_PIXELS / 32).
 *
 * Every lane runs the same instructions: until divergence is implemented, a
 * branch follows lane 0. So the border, |g| and the clamp are arithmetic, not
 * ifs, and the neighbours of a border pixel are clamped into the image (its
 * value is then masked to 0).
 */
#include "gpgpu_device.h"
#include "sobel.h"

GPGPU_DEVICE int image[SOBEL_PIXELS];
GPGPU_DEVICE int edges[SOBEL_PIXELS];

static inline int absolute(int v)
{
    int sign = v >> 31;
    return (v ^ sign) - sign;
}

GPGPU_GLOBAL void sobel(const int *in, int *out)
{
    int idx = (int)(gpgpu_block_idx_x() * gpgpu_block_dim() + gpgpu_thread_idx());
    int x = idx & (SOBEL_WIDTH - 1);
    int y = idx / SOBEL_WIDTH; /* a shift: SOBEL_WIDTH is a power of two */

    /* The neighbours' coordinates, clamped into the image. */
    int xm = x - (x > 0), xp = x + (x < SOBEL_WIDTH - 1);
    int ym = y - (y > 0), yp = y + (y < SOBEL_HEIGHT - 1);

    int p00 = in[ym * SOBEL_WIDTH + xm], p01 = in[ym * SOBEL_WIDTH + x], p02 = in[ym * SOBEL_WIDTH + xp];
    int p10 = in[y * SOBEL_WIDTH + xm], p12 = in[y * SOBEL_WIDTH + xp];
    int p20 = in[yp * SOBEL_WIDTH + xm], p21 = in[yp * SOBEL_WIDTH + x], p22 = in[yp * SOBEL_WIDTH + xp];

    int gx = (p02 + (p12 << 1) + p22) - (p00 + (p10 << 1) + p20);
    int gy = (p20 + (p21 << 1) + p22) - (p00 + (p01 << 1) + p02);
    int mag = absolute(gx) + absolute(gy);

    /* min(mag, 255): (255 - mag) >> 31 is -1 above 255, 0 otherwise. */
    mag -= (mag - 255) & ((255 - mag) >> 31);

    /* 0 on the border: xm == x or xp == x there. */
    int inside = (xm != x) & (xp != x) & (ym != y) & (yp != y);
    out[idx] = mag & -inside;
}
