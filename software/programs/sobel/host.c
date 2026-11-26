/*
 * sobel: the host program. Writes a test image, runs the kernel over one
 * thread per pixel and compares the edges with the straightforward
 * algorithm, with branches, run here.
 *
 * The image: left half black, right half white, and a white square in the
 * lower left, so there are vertical, horizontal and corner edges.
 */
#include "gpgpu.h"
#include "sobel_kernels.h"

#define W SOBEL_WIDTH
#define H SOBEL_HEIGHT

/* The reference: the original program's loop. */
static int reference(const int *image, int x, int y)
{
    if (x == 0 || x == W - 1 || y == 0 || y == H - 1)
        return 0;
    int p00 = image[(y - 1) * W + (x - 1)], p01 = image[(y - 1) * W + x], p02 = image[(y - 1) * W + (x + 1)];
    int p10 = image[y * W + (x - 1)], p12 = image[y * W + (x + 1)];
    int p20 = image[(y + 1) * W + (x - 1)], p21 = image[(y + 1) * W + x], p22 = image[(y + 1) * W + (x + 1)];
    int gx = (p02 + (p12 << 1) + p22) - (p00 + (p10 << 1) + p20);
    int gy = (p20 + (p21 << 1) + p22) - (p00 + (p01 << 1) + p02);
    if (gx < 0)
        gx = -gx;
    if (gy < 0)
        gy = -gy;
    int mag = gx + gy;
    return mag > 255 ? 255 : mag;
}

int gpgpu_main(int argc, char **argv)
{
    (void)argc;
    (void)argv;
    int image[SOBEL_PIXELS], edges[SOBEL_PIXELS];
    int wrong = 0;

    for (int y = 0; y < H; y++)
        for (int x = 0; x < W; x++)
            image[y * W + x] = x >= W / 2 || (y >= 10 && y < 14 && x >= 2 && x < 6) ? 255 : 0;
    GPGPU_CHECK(gpgpu_memcpy_to_symbol(sobel_sym_image, image, sizeof image, 0));

    GPGPU_CHECK(gpgpu_launch(sobel, gpgpu_dim3(SOBEL_PIXELS / GPGPU_BLOCK_SIZE), gpgpu_symbol_address(sobel_sym_image),
                             gpgpu_symbol_address(sobel_sym_edges)));
    GPGPU_CHECK(gpgpu_memcpy_from_symbol(edges, sobel_sym_edges, sizeof edges, 0));

    for (int y = 0; y < H; y++) {
        for (int x = 0; x < W; x++) {
            int want = reference(image, x, y);
            gpgpu_printf("%4d", edges[y * W + x]);
            wrong += edges[y * W + x] != want;
        }
        gpgpu_printf("\n");
    }
    gpgpu_printf("%s: %d of %d pixels differ from the reference\n", wrong ? "FAIL" : "PASS", wrong, SOBEL_PIXELS);
    return wrong ? 1 : 0;
}
