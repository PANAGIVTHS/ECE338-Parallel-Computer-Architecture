/*
 * pixels: the host program. Draws the three bars into a framebuffer, shows
 * it, then reads the framebuffer back and checks every pixel.
 *
 *   gpgpu_main([framebuffer])   default framebuffer 0
 */
#include <stdlib.h>

#include "gpgpu.h"
#include "pixels_kernels.h"

#define WIDTH  1280u
#define HEIGHT 720u

_Static_assert(WIDTH % GPGPU_BLOCK_SIZE == 0, "a row is whole stores of the lanes");

static unsigned int image[WIDTH * HEIGHT];

int gpgpu_main(int argc, char **argv)
{
    int n = argc > 1 ? atoi(argv[1]) : 0;
    unsigned int *fb = gpgpu_framebuffer(n);

    if (fb == NULL) {
        gpgpu_printf("framebuffer %d does not exist\n", n);
        return 1;
    }

    uint32_t start = gpgpu_time_ms();
    GPGPU_CHECK(gpgpu_launch(pixels, gpgpu_dim3(1, HEIGHT), fb, WIDTH));
    GPGPU_CHECK(gpgpu_synchronize());
    gpgpu_printf("pixels: framebuffer %d, %u ms\n", n, (unsigned)(gpgpu_time_ms() - start));
    GPGPU_CHECK(gpgpu_display(n));

    GPGPU_CHECK(gpgpu_memcpy(image, fb, sizeof image, GPGPU_DEVICE_TO_HOST));
    unsigned int wrong = 0;
    for (unsigned int y = 0; y < HEIGHT; y++)
        for (unsigned int x = 0; x < WIDTH; x++) {
            unsigned int want = bar_color(x, WIDTH), got = image[y * WIDTH + x];
            if (got != want && wrong++ < 4)
                gpgpu_printf("  pixel (%u, %u) is 0x%06x, expected 0x%06x\n", x, y, got, want);
        }
    gpgpu_printf("%s: %u of %u pixels differ\n", wrong ? "FAIL" : "PASS", wrong, WIDTH * HEIGHT);
    return wrong ? 1 : 0;
}
