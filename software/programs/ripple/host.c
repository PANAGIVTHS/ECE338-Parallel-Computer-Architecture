/*
 * ripple: the host program. Checks one frame pixel by pixel against
 * ripple_color(), then animates, alternating the framebuffers, and reports
 * the frame rate.
 *
 *   gpgpu_main([frames])   default 120; 0 runs until a key arrives
 */
#include <stdlib.h>

#include "gpgpu.h"
#include "gpgpu_frames.h"
#include "ripple_kernels.h"

#define WIDTH  1280u
#define HEIGHT 720u
#define CHECKED_FRAME 7u

_Static_assert(WIDTH % GPGPU_BLOCK_SIZE == 0, "a row is whole stores of the lanes");

static unsigned int pixels[WIDTH * HEIGHT];

static gpgpu_error_t draw(unsigned int *fb, unsigned int frame, void *context)
{
    (void)context;
    return gpgpu_launch(ripple, gpgpu_dim3(1, HEIGHT), fb, WIDTH, HEIGHT, frame);
}

int gpgpu_main(int argc, char **argv)
{
    unsigned int frames = argc > 1 ? (unsigned int)strtoul(argv[1], NULL, 0) : 120u;
    unsigned int *fb = gpgpu_framebuffer(1);
    unsigned int wrong = 0;

    GPGPU_CHECK(draw(fb, CHECKED_FRAME, NULL));
    GPGPU_CHECK(gpgpu_memcpy(pixels, fb, sizeof pixels, GPGPU_DEVICE_TO_HOST));
    for (unsigned int y = 0; y < HEIGHT; y++)
        for (unsigned int x = 0; x < WIDTH; x++) {
            unsigned int want = ripple_color(x, y, WIDTH, HEIGHT, CHECKED_FRAME), got = pixels[y * WIDTH + x];
            if (got != want && wrong++ < 4)
                gpgpu_printf("  pixel (%u, %u) is 0x%06x, expected 0x%06x\n", x, y, got, want);
        }
    gpgpu_printf("frame %u: %u of %u pixels differ\n", CHECKED_FRAME, wrong, WIDTH * HEIGHT);

    int failed = gpgpu_run_frames("ripple", frames, draw, NULL);
    gpgpu_printf("%s\n", wrong || failed ? "FAIL" : "PASS");
    return wrong || failed ? 1 : 0;
}
