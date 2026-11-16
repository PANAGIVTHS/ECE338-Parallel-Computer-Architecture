#ifndef GPGPU_DISPLAY_H
#define GPGPU_DISPLAY_H

#include "xil_types.h"
#include "gpgpu_platform.h"

/*
 * The HDMI scanout: an AXI VDMA reads one of the two framebuffers and streams
 * it to the video output, GPGPU_FB_WIDTH x GPGPU_FB_HEIGHT words of
 * 0x00RRGGBB. Its base address comes from the hardware's xparameters.h.
 *
 * For host programs that draw frame after frame (software/games): draw into
 * the framebuffer that is not shown, then show it. The monitor (main.c) has
 * its own copy of this code, with its `display` command's messages.
 */

#define GPGPU_DISPLAY_FRAMEBUFFERS 2U

/* Byte address of framebuffer `fb`: GPGPU_FB0_BASE or GPGPU_FB1_BASE. */
u32 gpgpu_display_address(u32 fb);

/* Reset the VDMA's read channel and start it on framebuffer `fb`. Returns 0,
 * or -1 after printing why it did not start. */
int gpgpu_display_start(u32 fb);

/* Show framebuffer `fb` from the next frame boundary on. Until then the
 * VDMA still reads the other one, for at most one refresh (17 ms at 60 Hz).
 * Restarts a stopped channel. Returns 0 or -1. */
int gpgpu_display_show(u32 fb);

/* The framebuffer last started or shown. */
u32 gpgpu_display_shown(void);

/* Stop the read channel and wait until it has no read in flight; a PL reset
 * needs that first (see main.c). Returns 0 or -1. */
int gpgpu_display_stop(void);

#endif /* GPGPU_DISPLAY_H */
