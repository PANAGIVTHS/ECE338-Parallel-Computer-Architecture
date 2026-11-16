#include "gpgpu_display.h"

#include "sleep.h"
#include "xil_io.h"
#include "xil_printf.h"
#include "xparameters.h"

#ifndef XPAR_XAXIVDMA_0_BASEADDR
#error "XPAR_XAXIVDMA_0_BASEADDR is not defined: the hardware has no AXI VDMA"
#endif

/* MM2S registers (PG020). Writing VSIZE starts the channel. */
#define VDMA_MM2S_VDMACR         0x00U
#define VDMA_MM2S_VDMASR         0x04U
#define VDMA_PARK_PTR            0x28U
#define VDMA_MM2S_VSIZE          0x50U
#define VDMA_MM2S_HSIZE          0x54U
#define VDMA_MM2S_FRMDLY_STRIDE  0x58U
#define VDMA_MM2S_START_ADDRESS  0x5CU  /* frame store n at + 4 * n */

#define VDMA_CR_RS               0x00000001U
#define VDMA_CR_RESET            0x00000004U  /* Circular_Park (bit 1) left 0: park mode */
#define VDMA_SR_HALTED           0x00000001U
#define VDMA_SR_ERRORS           0x00000070U  /* DMAIntErr, DMASlvErr, DMADecErr */
#define VDMA_PARK_RD_MASK        0x0000001FU

#define FB_STRIDE_BYTES          (GPGPU_FB_WIDTH * 4U)

/* Frame store n of the VDMA holds framebuffer n; the block design gives it
 * one frame store per framebuffer (c_num_fstores). */
static const u32 framebuffers[GPGPU_DISPLAY_FRAMEBUFFERS] = { GPGPU_FB0_BASE, GPGPU_FB1_BASE };
static u32 shown_fb = 0U;

static inline u32 vdma_read(u32 offset)
{
    return Xil_In32((UINTPTR)XPAR_XAXIVDMA_0_BASEADDR + offset);
}

static inline void vdma_write(u32 offset, u32 value)
{
    Xil_Out32((UINTPTR)XPAR_XAXIVDMA_0_BASEADDR + offset, value);
}

u32 gpgpu_display_address(u32 fb)
{
    return framebuffers[fb % GPGPU_DISPLAY_FRAMEBUFFERS];
}

u32 gpgpu_display_shown(void)
{
    return shown_fb;
}

int gpgpu_display_stop(void)
{
    u32 timeout = 1000U;

    vdma_write(VDMA_MM2S_VDMACR, vdma_read(VDMA_MM2S_VDMACR) & ~VDMA_CR_RS);
    while ((vdma_read(VDMA_MM2S_VDMASR) & VDMA_SR_HALTED) == 0U) {
        if (--timeout == 0U) {
            xil_printf("ERROR: VDMA did not halt (MM2S_VDMASR=0x%08x)\r\n",
                       (unsigned int)vdma_read(VDMA_MM2S_VDMASR));
            return -1;
        }
        usleep(1);
    }
    return 0;
}

int gpgpu_display_start(u32 fb)
{
    u32 timeout = 1000U;

    if (fb >= GPGPU_DISPLAY_FRAMEBUFFERS) {
        xil_printf("ERROR: framebuffer %u does not exist (0..%u)\r\n", (unsigned int)fb,
                   (unsigned int)GPGPU_DISPLAY_FRAMEBUFFERS - 1U);
        return -1;
    }

    vdma_write(VDMA_MM2S_VDMACR, VDMA_CR_RESET);
    while ((vdma_read(VDMA_MM2S_VDMACR) & VDMA_CR_RESET) != 0U) {
        if (--timeout == 0U) {
            xil_printf("ERROR: VDMA reset did not complete\r\n");
            return -1;
        }
        usleep(1);
    }

    vdma_write(VDMA_MM2S_VDMACR, VDMA_CR_RS);
    for (u32 i = 0; i < GPGPU_DISPLAY_FRAMEBUFFERS; i++)
        vdma_write(VDMA_MM2S_START_ADDRESS + 4U * i, framebuffers[i]);
    vdma_write(VDMA_PARK_PTR, fb & VDMA_PARK_RD_MASK);
    vdma_write(VDMA_MM2S_FRMDLY_STRIDE, FB_STRIDE_BYTES);
    vdma_write(VDMA_MM2S_HSIZE, FB_STRIDE_BYTES);
    vdma_write(VDMA_MM2S_VSIZE, GPGPU_FB_HEIGHT);

    if ((vdma_read(VDMA_MM2S_VDMASR) & (VDMA_SR_HALTED | VDMA_SR_ERRORS)) != 0U) {
        xil_printf("ERROR: VDMA did not start (MM2S_VDMASR=0x%08x)\r\n",
                   (unsigned int)vdma_read(VDMA_MM2S_VDMASR));
        return -1;
    }

    shown_fb = fb;
    return 0;
}

int gpgpu_display_show(u32 fb)
{
    u32 status = vdma_read(VDMA_MM2S_VDMASR);

    if (fb >= GPGPU_DISPLAY_FRAMEBUFFERS) {
        xil_printf("ERROR: framebuffer %u does not exist (0..%u)\r\n", (unsigned int)fb,
                   (unsigned int)GPGPU_DISPLAY_FRAMEBUFFERS - 1U);
        return -1;
    }
    if ((status & (VDMA_SR_HALTED | VDMA_SR_ERRORS)) != 0U) {
        xil_printf("VDMA stopped (MM2S_VDMASR=0x%08x); restarting\r\n", (unsigned int)status);
        return gpgpu_display_start(fb);
    }

    vdma_write(VDMA_PARK_PTR, fb & VDMA_PARK_RD_MASK);
    shown_fb = fb;
    return 0;
}
