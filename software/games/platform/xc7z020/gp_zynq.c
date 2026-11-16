#include "../gp_port.h"

#include "gpgpu_display.h"
#include "gpgpu_driver.h"

#include "sleep.h"
#include "xcortexa9_config.h"
#include "xil_cache.h"
#include "xil_io.h"
#include "xil_printf.h"
#include "xiltimer.h"
#include "xparameters.h"
#include "xuartps_hw.h"

#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/time.h>

/*
 * The platform on the board: a Zynq-7000 with the GPGPU in its fabric.
 *
 * Time is the Cortex-A9 global timer, the console is the PS UART, the GPU is
 * reached through the host driver (software/host/xc7z020), and the display
 * is the VDMA's two framebuffers. GMEM and the framebuffers are plain DDR to
 * the ARM, at the addresses the GPU uses.
 *
 * The GPU reads and writes DDR through a PS port that goes around the ARM's
 * caches. gp_gmem_sync() writes the ARM's cached lines of a range back to
 * DDR and drops them, which serves both directions: the GPU sees what the
 * game wrote, and the game's next read fetches what the GPU wrote.
 */

extern char inbyte(void);

/* The linker script's heap and stack (lscript.ld). */
extern char _heap_start[], _heap_end[], _stack_end[], __stack[];

static unsigned int lanes;

/* XTime_GetTime counts at half the CPU clock. XilTimer starts that timer on
 * the first sleep call, so gp_port_init() sleeps once before any reading. */
uint32_t gp_time_ms(void)
{
    XTime now;

    XTime_GetTime(&now);
    return (uint32_t)((u64)now * 1000U / (XGet_CpuFreq() / 2U));
}

void gp_sleep_ms(uint32_t ms)
{
    usleep((useconds_t)ms * 1000U);
}

int gp_port_console_read(void)
{
    return XUartPs_IsReceiveData(STDIN_BASEADDRESS) ? (int)(unsigned char)inbyte() : -1;
}

char **gp_port_arguments(char **configured)
{
    return configured;
}

void gp_port_halt(int status)
{
    xil_printf("\r\n%s halted (status %d). Program the board again to restart.\r\n", GP_GAME_NAME, status);
    for (;;) {
    }
}

void gp_port_gmem(uint8_t **base, size_t *bytes)
{
    *base = (uint8_t *)(UINTPTR)GPGPU_GMEM_BASE;
    *bytes = GPGPU_GMEM_SIZE;
}

void gp_gmem_sync(const void *pointer, size_t bytes)
{
    if (bytes != 0)
        Xil_DCacheFlushRange((INTPTR)pointer, (u32)bytes);
}

unsigned int gp_gpu_lanes(void)
{
    return lanes;
}

void gp_gpu_set_arg(unsigned int index, uint32_t value)
{
    if (index >= gp_kernel_args || gpgpu_write_dmem(gp_kernel_args_word + index, value) != GPGPU_OK)
        gp_fatal("cannot write kernel argument %u", index);
}

int gp_port_gpu_run(void)
{
    if (gpgpu_run_quiet() == GPGPU_OK)
        return 0;
    gpgpu_print_status();
    return -1;
}

void gp_port_display(unsigned int *width, unsigned int *height, uint32_t *stride)
{
    *width = GPGPU_FB_WIDTH;
    *height = GPGPU_FB_HEIGHT;
    *stride = GPGPU_FB_WIDTH * 4U;
}

uint32_t gp_port_display_hidden(void)
{
    return gpgpu_display_address(gpgpu_display_shown() ^ 1U);
}

/*
 * The VDMA switches at its next frame boundary, so it may still read the
 * other framebuffer for up to one refresh. A game draws its next picture
 * into that one, but only at the end of its next frame, which is later than
 * that unless the frame takes under 17 ms.
 */
void gp_display_flip(void)
{
    if (gpgpu_display_show(gpgpu_display_shown() ^ 1U) != 0)
        gp_fatal("the display did not switch framebuffers");
}

static void load_kernel(void)
{
    u32 word;

    for (unsigned int i = 0; i < gp_kernel_words; i++) {
        if (gpgpu_write_imem(i, gp_kernel_image[i]) != GPGPU_OK || gpgpu_read_imem(i, &word) != GPGPU_OK ||
            word != gp_kernel_image[i])
            gp_fatal("IMEM word %u did not load", i);
    }
    gp_log("%s: kernel of %u instructions loaded\r\n", GP_GAME_NAME, gp_kernel_words);
}

void gp_port_init(void)
{
    /* The UART is the console: nothing may wait in a buffer when a game stops. */
    setvbuf(stdout, NULL, _IONBF, 0);
    usleep(1);
    xil_printf("\r\n%s on the GPGPU\r\n", GP_GAME_NAME);

    /* The build links with --defsym for these (software.games.platform.memory).
     * Too small a stack fails later and silently, so check now. */
    if ((size_t)(_heap_end - _heap_start) < GP_HEAP_BYTES || (size_t)(__stack - _stack_end) < GP_STACK_BYTES)
        gp_fatal("linked with %lu bytes of heap and %lu of stack; the game needs %lu and %lu "
                 "(the linker's --defsym=_HEAP_SIZE and _STACK_SIZE did not apply)",
                 (unsigned long)(_heap_end - _heap_start), (unsigned long)(__stack - _stack_end),
                 (unsigned long)GP_HEAP_BYTES, (unsigned long)GP_STACK_BYTES);

    if (gpgpu_init() != GPGPU_OK)
        gp_fatal("the GPU did not initialize");
    lanes = Xil_In32((UINTPTR)GPGPU_BASEADDR + GPGPU_REG_INFO) & GPGPU_INFO_SP_COUNT_MASK;
    if ((Xil_In32((UINTPTR)GPGPU_BASEADDR + GPGPU_REG_INFO_FEATURES) & GPGPU_FEATURE_DDR_MASK) == 0U)
        gp_fatal("this bitstream has no DDR backend (architecture.ddr_enable): the GPU cannot reach GMEM");
    /* A kernel steps through its work by its lane count: it must be the GPU's. */
    if (lanes != gp_kernel_lanes)
        gp_fatal("the kernel was built for %u lanes (architecture.num_cores) and the GPU has %u: "
                 "rebuild the game with the bitstream's configuration", gp_kernel_lanes, lanes);
    load_kernel();

    for (u32 fb = 0; fb < GPGPU_DISPLAY_FRAMEBUFFERS; fb++) {
        void *pixels = (void *)(UINTPTR)gpgpu_display_address(fb);

        memset(pixels, 0, GPGPU_FB_SIZE);
        Xil_DCacheFlushRange((INTPTR)pixels, GPGPU_FB_SIZE);
    }
    if (gpgpu_display_start(0U) != 0)
        gp_fatal("the display did not start");

    /* Drop what the UART received before now: the EMIO RX pin is undriven
     * until the bitstream loads, and that latches junk bytes in the FIFO. */
    while (XUartPs_IsReceiveData(STDIN_BASEADDRESS))
        (void)inbyte();
}

int main(void)
{
    gp_main();
}

/*
 * C library calls a desktop game makes and the board's library does not
 * have: there are no directories, and no files to rename or remove. Weak,
 * so a library that does provide one wins.
 */
__attribute__((weak)) int mkdir(const char *path, mode_t mode)
{
    (void)path;
    (void)mode;
    errno = ENOSYS;
    return -1;
}

__attribute__((weak)) int _link(const char *existing, const char *created)
{
    (void)existing;
    (void)created;
    errno = ENOSYS;
    return -1;
}

__attribute__((weak)) int _unlink(const char *path)
{
    (void)path;
    errno = ENOSYS;
    return -1;
}
