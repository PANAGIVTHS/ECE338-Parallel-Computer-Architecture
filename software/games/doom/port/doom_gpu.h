#ifndef DOOM_GPU_H
#define DOOM_GPU_H

/*
 * The port's own interface: doom_video.c owns DOOM's screen and palette,
 * doom_render.c records what DOOM draws into it and runs the kernel.
 */

#include <stdint.h>

/* Once, with DOOM's screen (in GMEM) and its palette of 256 0x00RRGGBB words. */
void doom_gpu_init(uint8_t *screen, const uint32_t *palette);

/* Show the screen: scale it into the hidden framebuffer and flip. */
void doom_gpu_present(void);

#endif /* DOOM_GPU_H */
