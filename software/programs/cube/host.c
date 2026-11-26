/*
 * cube: the host program. Runs cube_setup() for each frame, checks one frame
 * pixel by pixel against the spans evaluated here, then animates,
 * alternating the framebuffers, and reports the frame rate.
 *
 *   gpgpu_main([frames])   default 120; 0 runs until a key arrives
 */
#include <stdlib.h>

#include "gpgpu.h"
#include "gpgpu_frames.h"
#include "cube_kernels.h"

#define WIDTH  1280
#define HEIGHT 720
#define CHECKED_FRAME 33

_Static_assert(WIDTH % GPGPU_BLOCK_SIZE == 0 && WIDTH <= 2048, "a row is whole stores of the lanes");

static unsigned int pixels[WIDTH * HEIGHT];

static gpgpu_error_t draw(unsigned int *fb, unsigned int frame, void *context)
{
    cube_t cube;

    (void)context;
    cube_setup(&cube, WIDTH, HEIGHT, (int)frame);
    gpgpu_error_t error = gpgpu_memcpy_to_symbol(cube_sym_frame_cube, &cube, sizeof cube, 0);
    if (error != GPGPU_SUCCESS)
        return error;
    return gpgpu_launch(cube_kernel, gpgpu_dim3(1), fb, WIDTH, HEIGHT, gpgpu_symbol_address(cube_sym_frame_cube));
}

int gpgpu_main(int argc, char **argv)
{
    unsigned int frames = argc > 1 ? (unsigned int)strtoul(argv[1], NULL, 0) : 120u;
    unsigned int *fb = gpgpu_framebuffer(1);
    cube_t cube;
    unsigned int wrong = 0;

    GPGPU_CHECK(draw(fb, CHECKED_FRAME, NULL));
    GPGPU_CHECK(gpgpu_memcpy(pixels, fb, sizeof pixels, GPGPU_DEVICE_TO_HOST));
    cube_setup(&cube, WIDTH, HEIGHT, CHECKED_FRAME);
    for (int y = 0; y < HEIGHT; y++) {
        int xl[SLOTS], w[SLOTS];

        for (int s = 0; s < SLOTS; s++)
            face_span(&cube, s, y, &xl[s], &w[s]);
        for (int x = 0; x < WIDTH; x++) {
            unsigned int want = background(y), got = pixels[y * WIDTH + x];
            for (int s = 0; s < SLOTS; s++)
                want = (unsigned int)select_mask(in_span(x, xl[s], w[s]), (int)cube.slot[s].color, (int)want);
            if (got != want && wrong++ < 4)
                gpgpu_printf("  pixel (%d, %d) is 0x%06x, expected 0x%06x\n", x, y, got, want);
        }
    }
    gpgpu_printf("frame %d: %u of %d pixels differ\n", CHECKED_FRAME, wrong, WIDTH * HEIGHT);

    int failed = gpgpu_run_frames("cube", frames, draw, NULL);
    gpgpu_printf("%s\n", wrong || failed ? "FAIL" : "PASS");
    return wrong || failed ? 1 : 0;
}
