/*
 * metaballs: the host program. Computes each frame's balls, checks one frame
 * pixel by pixel against the fields evaluated here, then animates,
 * alternating the framebuffers, and reports the frame rate.
 *
 *   gpgpu_main([frames])   default 120; 0 runs until a key arrives
 */
#include <stdlib.h>

#include "gpgpu.h"
#include "gpgpu_frames.h"
#include "metaballs_kernels.h"

#define WIDTH  1280
#define HEIGHT 720
#define CHECKED_FRAME 40

_Static_assert(WIDTH % GPGPU_BLOCK_SIZE == 0, "a row is whole stores of the lanes");

static unsigned int pixels[WIDTH * HEIGHT];

static gpgpu_error_t draw(unsigned int *fb, unsigned int frame, void *context)
{
    balls_t b;

    (void)context;
    ball_positions(&b, WIDTH, HEIGHT, (int)frame);
    gpgpu_error_t error = gpgpu_memcpy_to_symbol(metaballs_sym_balls, &b, sizeof b, 0);
    if (error != GPGPU_SUCCESS)
        return error;
    return gpgpu_launch(metaballs, gpgpu_dim3(1, HEIGHT), fb, WIDTH, gpgpu_symbol_address(metaballs_sym_balls));
}

int gpgpu_main(int argc, char **argv)
{
    unsigned int frames = argc > 1 ? (unsigned int)strtoul(argv[1], NULL, 0) : 120u;
    unsigned int *fb = gpgpu_framebuffer(1);
    balls_t b;
    unsigned int wrong = 0;

    GPGPU_CHECK(draw(fb, CHECKED_FRAME, NULL));
    GPGPU_CHECK(gpgpu_memcpy(pixels, fb, sizeof pixels, GPGPU_DEVICE_TO_HOST));
    ball_positions(&b, WIDTH, HEIGHT, CHECKED_FRAME);
    for (int y = 0; y < HEIGHT; y++)
        for (int x = 0; x < WIDTH; x++) {
            int field = 0;
            for (int i = 0; i < BALLS; i++)
                field += ball_field(ball_reach(b.r2[i], y - b.y[i]), x - b.x[i]);
            unsigned int want = field_color(field, y), got = pixels[y * WIDTH + x];
            if (got != want && wrong++ < 4)
                gpgpu_printf("  pixel (%d, %d) is 0x%06x, expected 0x%06x\n", x, y, got, want);
        }
    gpgpu_printf("frame %d: %u of %d pixels differ\n", CHECKED_FRAME, wrong, WIDTH * HEIGHT);

    int failed = gpgpu_run_frames("metaballs", frames, draw, NULL);
    gpgpu_printf("%s\n", wrong || failed ? "FAIL" : "PASS");
    return wrong || failed ? 1 : 0;
}
