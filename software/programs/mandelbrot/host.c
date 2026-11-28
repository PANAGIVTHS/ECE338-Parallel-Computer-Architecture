/*
 * mandelbrot: the host program. Computes each frame's view with mandel_setup()
 * (mandelbrot.c), checks one frame sample by sample against fractal_sample(),
 * then animates, alternating the framebuffers, and reports the frame rate.
 *
 *   gpgpu_main([frames])   default 60; 0 runs until a key arrives
 */
#include <stdlib.h>

#include "gpgpu.h"
#include "gpgpu_frames.h"
#include "mandelbrot_kernels.h"

#define WIDTH  1280
#define HEIGHT 720
#define CHECKED_FRAME 9

_Static_assert(WIDTH % (FRACTAL_BLOCK * GPGPU_BLOCK_SIZE) == 0 && HEIGHT % FRACTAL_BLOCK == 0, "whole 2x2 samples");

static unsigned int pixels[WIDTH * HEIGHT];

static gpgpu_error_t draw(unsigned int *fb, unsigned int frame, void *context)
{
    fractal_t view;

    (void)context;
    mandel_setup(&view, (int)frame);
    gpgpu_error_t error = gpgpu_memcpy_to_symbol(mandelbrot_sym_view, &view, sizeof view, 0);
    if (error != GPGPU_SUCCESS)
        return error;
    return gpgpu_launch(mandelbrot, gpgpu_dim3(1, HEIGHT / FRACTAL_BLOCK), fb, WIDTH, HEIGHT, (int)frame,
                        gpgpu_symbol_address(mandelbrot_sym_view));
}

int gpgpu_main(int argc, char **argv)
{
    unsigned int frames = argc > 1 ? (unsigned int)strtoul(argv[1], NULL, 0) : 60u;
    unsigned int *fb = gpgpu_framebuffer(1);
    fractal_t view;
    unsigned int wrong = 0;

    GPGPU_CHECK(draw(fb, CHECKED_FRAME, NULL));
    GPGPU_CHECK(gpgpu_memcpy(pixels, fb, sizeof pixels, GPGPU_DEVICE_TO_HOST));
    mandel_setup(&view, CHECKED_FRAME);
    for (int y = 0; y < HEIGHT; y++)
        for (int x = 0; x < WIDTH; x++) {
            /* The sample of the 2x2 block the pixel is in. */
            unsigned int want = fractal_sample(x & ~(FRACTAL_BLOCK - 1), y & ~(FRACTAL_BLOCK - 1), WIDTH, HEIGHT,
                                               CHECKED_FRAME, &view);
            unsigned int got = pixels[y * WIDTH + x];
            if (got != want && wrong++ < 4)
                gpgpu_printf("  pixel (%d, %d) is 0x%06x, expected 0x%06x\n", x, y, got, want);
        }
    gpgpu_printf("frame %d: %u of %d pixels differ\n", CHECKED_FRAME, wrong, WIDTH * HEIGHT);

    int failed = gpgpu_run_frames("mandelbrot", frames, draw, NULL);
    gpgpu_printf("%s\n", wrong || failed ? "FAIL" : "PASS");
    return wrong || failed ? 1 : 0;
}
