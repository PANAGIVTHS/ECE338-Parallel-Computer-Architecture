/*
 * fill: the host program. Draws the checkerboard into a framebuffer, shows
 * it, then reads the framebuffer back and checks every pixel.
 *
 *   gpgpu_main([c0 [c1 [framebuffer]]])   colors 0x00RRGGBB, default black and white, framebuffer 0
 */
#include <stdlib.h>

#include "gpgpu.h"
#include "fill_kernels.h"

#define WIDTH  1280u
#define HEIGHT 720u

_Static_assert(WIDTH % GPGPU_BLOCK_SIZE == 0, "a row is whole stores of the lanes");

static unsigned int pixels[WIDTH * HEIGHT];

int gpgpu_main(int argc, char **argv)
{
    unsigned int c0 = argc > 1 ? (unsigned int)strtoul(argv[1], NULL, 0) : 0x000000u;
    unsigned int c1 = argc > 2 ? (unsigned int)strtoul(argv[2], NULL, 0) : 0xFFFFFFu;
    int n = argc > 3 ? atoi(argv[3]) : 0;
    unsigned int *fb = gpgpu_framebuffer(n);

    if (fb == NULL) {
        gpgpu_printf("framebuffer %d does not exist\n", n);
        return 1;
    }

    uint32_t start = gpgpu_time_ms();
    GPGPU_CHECK(gpgpu_launch(fill, gpgpu_dim3(1, HEIGHT), fb, WIDTH, c0, c1));
    GPGPU_CHECK(gpgpu_synchronize());
    gpgpu_printf("fill: framebuffer %d, colors 0x%06x and 0x%06x, %u ms\n", n, c0, c1,
                 (unsigned)(gpgpu_time_ms() - start));
    GPGPU_CHECK(gpgpu_display(n));

    GPGPU_CHECK(gpgpu_memcpy(pixels, fb, sizeof pixels, GPGPU_DEVICE_TO_HOST));
    unsigned int wrong = 0;
    for (unsigned int y = 0; y < HEIGHT; y++)
        for (unsigned int x = 0; x < WIDTH; x++) {
            unsigned int want = fill_color(x, y, c0, c1), got = pixels[y * WIDTH + x];
            if (got != want && wrong++ < 4)
                gpgpu_printf("  pixel (%u, %u) is 0x%06x, expected 0x%06x\n", x, y, got, want);
        }
    gpgpu_printf("%s: %u of %u pixels differ\n", wrong ? "FAIL" : "PASS", wrong, WIDTH * HEIGHT);
    return wrong ? 1 : 0;
}
