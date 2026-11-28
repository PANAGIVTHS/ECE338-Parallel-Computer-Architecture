/*
 * terrain: the host program. Checks one frame pixel by pixel against the
 * native build of terrain.h (terrain_reference), then flies, alternating the
 * framebuffers, and reports the frame rate.
 *
 *   gpgpu_main([frames])   default 120; 0 runs until a key arrives
 */
#include <stdlib.h>

#include "gpgpu.h"
#include "gpgpu_frames.h"
#include "terrain_kernels.h"

#define WIDTH  1280
#define HEIGHT 720
#define CHECKED_FRAME 25

_Static_assert(WIDTH % CORES == 0 && WIDTH <= CORES * MAX_TILES && HEIGHT % TILE_H == 0,
               "whole tiles of 32 x 8 pixels");

static unsigned int pixels[WIDTH * HEIGHT];
static unsigned int reference[WIDTH * HEIGHT];

static gpgpu_error_t draw(unsigned int *fb, unsigned int frame, void *context)
{
    (void)context;
    return gpgpu_launch(terrain, gpgpu_dim3(1), fb, WIDTH, HEIGHT, (int)frame);
}

int gpgpu_main(int argc, char **argv)
{
    unsigned int frames = argc > 1 ? (unsigned int)strtoul(argv[1], NULL, 0) : 120u;
    unsigned int *fb = gpgpu_framebuffer(1);
    unsigned int wrong = 0;

    GPGPU_CHECK(draw(fb, CHECKED_FRAME, NULL));
    GPGPU_CHECK(gpgpu_memcpy(pixels, fb, sizeof pixels, GPGPU_DEVICE_TO_HOST));
    terrain_reference(reference, WIDTH, HEIGHT, CHECKED_FRAME);
    for (int i = 0; i < WIDTH * HEIGHT; i++)
        if (pixels[i] != reference[i] && wrong++ < 4)
            gpgpu_printf("  pixel (%d, %d) is 0x%06x, expected 0x%06x\n", i % WIDTH, i / WIDTH, pixels[i],
                         reference[i]);
    gpgpu_printf("frame %d: %u of %d pixels differ\n", CHECKED_FRAME, wrong, WIDTH * HEIGHT);

    int failed = gpgpu_run_frames("terrain", frames, draw, NULL);
    gpgpu_printf("%s\n", wrong || failed ? "FAIL" : "PASS");
    return wrong || failed ? 1 : 0;
}
