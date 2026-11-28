#ifndef GPGPU_FRAMES_H
#define GPGPU_FRAMES_H

/*
 * The frame loop of host programs that animate (ripple, julia, ...): draw each
 * frame into the framebuffer the display is not showing, show it, and report
 * the frame rate. Host side only.
 *
 *   static gpgpu_error_t draw(unsigned int *fb, unsigned int frame, void *context);
 *   gpgpu_run_frames("ripple", frames, draw, &context);
 *
 * frames 0 runs until a key arrives on the console.
 */

#include "gpgpu.h"

typedef gpgpu_error_t (*gpgpu_frame_fn)(unsigned int *fb, unsigned int frame, void *context);

static inline int gpgpu_run_frames(const char *name, unsigned int frames, gpgpu_frame_fn draw, void *context)
{
    uint32_t start = gpgpu_time_ms();
    unsigned int frame = 0;

    while (frames == 0 || frame < frames) {
        int hidden = (int)((frame + 1u) & 1u);
        gpgpu_error_t error = draw(gpgpu_framebuffer(hidden), frame, context);
        if (error == GPGPU_SUCCESS)
            error = gpgpu_display(hidden); /* waits for the frame's kernel */
        if (error != GPGPU_SUCCESS) {
            gpgpu_printf("%s: frame %u: %s\n", name, frame, gpgpu_error_string(error));
            return 1;
        }
        frame++;
        if (frames == 0 && gpgpu_key() >= 0)
            break;
    }
    uint32_t elapsed = gpgpu_time_ms() - start;
    unsigned int centi = elapsed ? (unsigned int)((frame * 100000ull) / elapsed) : 0u;
    gpgpu_printf("%s: %u frames in %u ms, %u.%02u frames/s\n", name, frame, (unsigned)elapsed, centi / 100u,
                 centi % 100u);
    return 0;
}

#endif /* GPGPU_FRAMES_H */
