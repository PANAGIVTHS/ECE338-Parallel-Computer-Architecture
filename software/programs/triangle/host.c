/*
 * triangle: the host program. Draws a triangle over the whole framebuffer,
 * then one into a narrower picture whose width is not a multiple of 32 (the
 * tail chunk), and compares every pixel with the edge functions evaluated
 * directly, without the kernel's incremental stepping.
 *
 *   gpgpu_main([x0 y0 x1 y1 x2 y2 [color [background]]])
 */
#include <stdlib.h>

#include "gpgpu.h"
#include "triangle_kernels.h"

#define WIDTH  1280
#define HEIGHT 720

static unsigned int pixels[WIDTH * HEIGHT];

/* One picture: draw, read back, compare. The number of wrong pixels. */
static int draw(int n, int width, tri_params_t t)
{
    unsigned int *fb = gpgpu_framebuffer(n);
    edge_t a, b, c;
    unsigned int fg;
    int wrong = 0;

    GPGPU_CHECK(gpgpu_memcpy_to_symbol(triangle_sym_triangle_params, &t, sizeof t, 0));
    uint32_t start = gpgpu_time_ms();
    GPGPU_CHECK(gpgpu_launch(triangle, gpgpu_dim3(1, HEIGHT), fb, width,
                             gpgpu_symbol_address(triangle_sym_triangle_params)));
    GPGPU_CHECK(gpgpu_synchronize());
    uint32_t elapsed = gpgpu_time_ms() - start;
    GPGPU_CHECK(gpgpu_memcpy(pixels, fb, (size_t)width * HEIGHT * sizeof pixels[0], GPGPU_DEVICE_TO_HOST));

    triangle_setup(t, &a, &b, &c, &fg);
    for (int y = 0; y < HEIGHT; y++)
        for (int x = 0; x < width; x++) {
            int ea = a.value + a.step_x * x + a.step_y * y;
            int eb = b.value + b.step_x * x + b.step_y * y;
            int ec = c.value + c.step_x * x + c.step_y * y;
            unsigned int want = shade(inside_mask(ea, eb, ec), fg, t.background), got = pixels[y * width + x];
            if (got != want && wrong++ < 4)
                gpgpu_printf("  pixel (%d, %d) is 0x%06x, expected 0x%06x\n", x, y, got, want);
        }
    gpgpu_printf("framebuffer %d, %d x %d: %u ms, %d pixels differ\n", n, width, HEIGHT, (unsigned)elapsed, wrong);
    return wrong;
}

int gpgpu_main(int argc, char **argv)
{
    tri_params_t t = {100, 620, 640, 80, 1180, 650, 0x00FFAA00u, 0x00102040u};
    int *vertex = &t.x0;

    if (argc >= 7)
        for (int i = 0; i < 6; i++)
            vertex[i] = (int)strtol(argv[1 + i], NULL, 0);
    if (argc >= 8)
        t.color = (unsigned int)strtoul(argv[7], NULL, 0);
    if (argc >= 9)
        t.background = (unsigned int)strtoul(argv[8], NULL, 0);

    int wrong = draw(1, 1000, t); /* a tail chunk in every row */
    wrong += draw(0, WIDTH, t);
    GPGPU_CHECK(gpgpu_display(0));
    gpgpu_printf("%s\n", wrong ? "FAIL" : "PASS");
    return wrong ? 1 : 0;
}
