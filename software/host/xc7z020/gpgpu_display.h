#ifndef GPGPU_DISPLAY_H
#define GPGPU_DISPLAY_H

/*
 * HDMI scanout: the AXI VDMA's MM2S channel reads one framebuffer and streams
 * it to the video output. Frame store n of the VDMA holds framebuffer n. The
 * monitor (main.c) and the runtime of loaded programs both use it.
 */

#include "xil_types.h"

#define GPGPU_DISPLAY_FRAMEBUFFERS 2U

/* Byte address of framebuffer `fb`: GPGPU_FB0_BASE or GPGPU_FB1_BASE; 0 if none. */
u32 gpgpu_display_address(u32 fb);

/* Reset the read channel and start it parked on framebuffer `fb`. 0, or -1
 * after printing why. */
int gpgpu_display_start(u32 fb);

/* Show framebuffer `fb` from the next frame boundary on; restarts a stopped
 * channel. `verbose` prints which one. 0 or -1. */
int gpgpu_display_show(u32 fb, int verbose);

/* The framebuffer last started or shown. */
u32 gpgpu_display_shown(void);

/* Stop the read channel and wait until it has no read in flight: a PL reset
 * needs that first. 0 or -1. */
int gpgpu_display_stop(void);

#endif /* GPGPU_DISPLAY_H */
