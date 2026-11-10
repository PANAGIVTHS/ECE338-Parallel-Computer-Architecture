#include "gpgpu_driver.h"

#include "xparameters.h"
#include "xil_io.h"
#include "xil_printf.h"
#include "xil_types.h"
#include "xiltimer.h"
#include "xcortexa9_config.h"
#include "xuartps_hw.h"
#include "sleep.h"

#include "gpgpu_autorun.h"

#include <stdlib.h>
#include <string.h>
#include <ctype.h>

/* HDMI scanout: the AXI VDMA's MM2S channel reads one framebuffer and streams
 * it to the video output. The base address comes from the hardware's
 * xparameters.h. */
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
 * one frame store per framebuffer (c_num_fstores). Its MM2S_FRMSTORE register
 * is not built in, so the count cannot be read back. */
static const u32 framebuffers[] = { GPGPU_FB0_BASE, GPGPU_FB1_BASE };
#define FB_COUNT                 (sizeof(framebuffers) / sizeof(framebuffers[0]))

static u32 rx_buffer[GPGPU_MAX_WORDS];
static u32 shown_fb = 0U;
extern char inbyte(void);

static inline u32 vdma_read(u32 offset) {
    return Xil_In32((UINTPTR)XPAR_XAXIVDMA_0_BASEADDR + offset);
}

static inline void vdma_write(u32 offset, u32 value) {
    Xil_Out32((UINTPTR)XPAR_XAXIVDMA_0_BASEADDR + offset, value);
}

/* Stop the MM2S channel and wait until it halts, so it has no read in flight.
 * A PL reset with a VDMA read outstanding leaves that read's data in the PS
 * HP2 port, which only a system reset clears: every later read then returns
 * the data of an earlier one and the picture stays rotated by whole bursts. */
static int display_stop(void) {
    u32 timeout = 1000U;

    vdma_write(VDMA_MM2S_VDMACR, vdma_read(VDMA_MM2S_VDMACR) & ~VDMA_CR_RS);
    while ((vdma_read(VDMA_MM2S_VDMASR) & VDMA_SR_HALTED) == 0U) {
        if (--timeout == 0U) {
            xil_printf("ERROR: VDMA did not halt (MM2S_VDMASR=0x%08x)\r\n",
                       vdma_read(VDMA_MM2S_VDMASR));
            return -1;
        }
        usleep(1);
    }
    return 0;
}

/* Reset the MM2S channel and start it parked on framebuffer `fb`: it scans
 * that one buffer every frame until display_show() parks it on another. */
static int display_start(u32 fb) {
    u32 timeout = 1000U;

    vdma_write(VDMA_MM2S_VDMACR, VDMA_CR_RESET);
    while ((vdma_read(VDMA_MM2S_VDMACR) & VDMA_CR_RESET) != 0U) {
        if (--timeout == 0U) {
            xil_printf("ERROR: VDMA reset did not complete\r\n");
            return -1;
        }
        usleep(1);
    }

    if (fb >= FB_COUNT) {
        xil_printf("ERROR: framebuffer %u does not exist (0..%u)\r\n", fb, (u32)FB_COUNT - 1U);
        return -1;
    }

    vdma_write(VDMA_MM2S_VDMACR, VDMA_CR_RS);
    for (u32 i = 0; i < FB_COUNT; i++)
        vdma_write(VDMA_MM2S_START_ADDRESS + 4U * i, framebuffers[i]);
    vdma_write(VDMA_PARK_PTR, fb & VDMA_PARK_RD_MASK);
    vdma_write(VDMA_MM2S_FRMDLY_STRIDE, FB_STRIDE_BYTES);
    vdma_write(VDMA_MM2S_HSIZE, FB_STRIDE_BYTES);
    vdma_write(VDMA_MM2S_VSIZE, GPGPU_FB_HEIGHT);

    if ((vdma_read(VDMA_MM2S_VDMASR) & (VDMA_SR_HALTED | VDMA_SR_ERRORS)) != 0U) {
        xil_printf("ERROR: VDMA did not start (MM2S_VDMASR=0x%08x)\r\n",
                   vdma_read(VDMA_MM2S_VDMASR));
        return -1;
    }

    shown_fb = fb;
    xil_printf("Display: FB%u at 0x%08x, %ux%u\r\n", fb, framebuffers[fb],
               GPGPU_FB_WIDTH, GPGPU_FB_HEIGHT);
    return 0;
}

/* Park the running channel on framebuffer `fb`; it switches at the next
 * frame boundary. */
static int display_show(u32 fb) {
    u32 status = vdma_read(VDMA_MM2S_VDMASR);

    if ((status & (VDMA_SR_HALTED | VDMA_SR_ERRORS)) != 0U) {
        xil_printf("VDMA stopped (MM2S_VDMASR=0x%08x); restarting\r\n", status);
        return display_start(fb);
    }
    if (fb >= FB_COUNT) {
        xil_printf("ERROR: framebuffer %u does not exist (0..%u)\r\n", fb, (u32)FB_COUNT - 1U);
        return -1;
    }

    vdma_write(VDMA_PARK_PTR, fb & VDMA_PARK_RD_MASK);
    shown_fb = fb;
    xil_printf("Display: FB%u at 0x%08x\r\n", fb, framebuffers[fb]);
    return 0;
}

/* Run the loaded kernel `frames` times back to back and report the rate, then
 * the performance counters of all the runs added up (the GPU clears them at
 * every START, so they are read after each run) and the result of their
 * consistency checks. The kernel must need no host writes between runs (e.g.
 * it advances its own frame counter). The time covers each run's START to
 * completion and the driver's checks, not the counter reads or UART traffic.
 *
 * XTime_GetTime (XilTimer) reads the Cortex-A9 global timer, which counts at
 * half the CPU clock. XilTimer starts that timer on the first sleep call, so
 * one usleep() comes first. */
static int bench(u32 frames) {
    const u64 counts_per_second = XGet_CpuFreq() / 2U;
    static gpgpu_perf_t total, run;
    XTime start, end;
    u64 elapsed = 0U, rate_x100;

    if (frames == 0U) {
        xil_printf("ERROR: bench needs at least one frame\r\n");
        return -1;
    }

    usleep(1);
    memset(&total, 0, sizeof(total));
    for (u32 i = 0; i < frames; i++) {
        XTime_GetTime(&start);
        if (gpgpu_run_quiet() != GPGPU_OK) {
            xil_printf("ERROR: frame %u failed\r\n", i);
            return -1;
        }
        XTime_GetTime(&end);
        elapsed += end - start;
        if (gpgpu_perf_read(&run) != GPGPU_OK)
            return -1;
        gpgpu_perf_add(&total, &run);
    }

    /* xil_printf has no floats or 64-bit integers: print fixed point. */
    rate_x100 = ((u64)frames * counts_per_second * 100U) / elapsed;
    xil_printf("%u frames in %u us: %u.%02u frames/s, %u us/frame\r\n", frames,
               (u32)((elapsed * 1000000U) / counts_per_second),
               (u32)(rate_x100 / 100U), (u32)(rate_x100 % 100U),
               (u32)((elapsed * 1000000U) / counts_per_second / frames));

    gpgpu_perf_print(&total, frames);
    if (gpgpu_perf_check(&total) == 0U)
        xil_printf("  Perf checks: all passed\r\n");
    return 0;
}

#if GPGPU_AUTORUN
#define AUTORUN_IMAGE_WORDS (sizeof(gpgpu_autorun_image) / sizeof(gpgpu_autorun_image[0]))
#define AUTORUN_ARG_WORDS   (sizeof(gpgpu_autorun_args) / sizeof(gpgpu_autorun_args[0]))

_Static_assert(AUTORUN_IMAGE_WORDS <= GPGPU_IMEM_ENTRIES, "autorun image does not fit IMEM");

/* Load the configured program (gpgpu_autorun.h, software.host.autorun) and run
 * it back to back until a key arrives on the UART or a run fails; then the
 * monitor starts. The key is consumed. The kernel must need no host writes
 * between runs (ripple advances its own frame counter). */
static void autorun(void) {
    u32 word, runs = 0U;

    for (u32 i = 0U; i < AUTORUN_IMAGE_WORDS; i++) {
        if (gpgpu_write_imem(i, gpgpu_autorun_image[i]) != 0 ||
            gpgpu_read_imem(i, &word) != 0 || word != gpgpu_autorun_image[i]) {
            xil_printf("AUTORUN: IMEM word %u did not load\r\n", i);
            return;
        }
    }
    for (u32 i = 0U; i < AUTORUN_ARG_WORDS; i++) {
        if (gpgpu_write_dmem(GPGPU_AUTORUN_ARGS_WORD + i, gpgpu_autorun_args[i]) != 0) {
            xil_printf("AUTORUN: argument word %u did not load\r\n", i);
            return;
        }
    }
    if (display_show(GPGPU_AUTORUN_DISPLAY) != 0)
        return;

    xil_printf("AUTORUN: %s, args", GPGPU_AUTORUN_PROGRAM);
    for (u32 i = 0U; i < AUTORUN_ARG_WORDS; i++)
        xil_printf(" 0x%08x", gpgpu_autorun_args[i]);
    xil_printf("; press a key to stop\r\n");

    /* Drop what the UART received before now: the EMIO RX pin is undriven
     * until the bitstream loads, and that latches junk bytes in the FIFO. */
    while (XUartPs_IsReceiveData(STDIN_BASEADDRESS))
        (void)inbyte();

    while (!XUartPs_IsReceiveData(STDIN_BASEADDRESS)) {
        if (gpgpu_run_quiet() != GPGPU_OK) {
            xil_printf("AUTORUN: run %u failed\r\n", runs);
            gpgpu_print_status();
            return;
        }
        runs++;
    }
    (void)inbyte();
    xil_printf("AUTORUN: stopped after %u runs\r\n", runs);
}
#endif

static void read_line(char *buf, int max_len) {
    int idx = 0;

    while (idx < max_len - 1) {
        char c = inbyte();

        if (c == '\r' || c == '\n') {
            xil_printf("\r\n");
            break;
        }

        if ((c == '\b' || c == 127) && idx > 0) {
            idx--;
            xil_printf("\b \b");
            continue;
        }

        buf[idx++] = c;
        xil_printf("%c", c);
    }

    buf[idx] = '\0';
}

static void trim(char *s) {
    int len;

    while (isspace((unsigned char)*s))
        memmove(s, s + 1, strlen(s));

    len = strlen(s);

    while (len > 0 && isspace((unsigned char)s[len - 1])) {
        s[len - 1] = '\0';
        len--;
    }
}

static int parse_u32_hex(const char *s, u32 *out) {
    char *endptr;
    unsigned long val;

    while (isspace((unsigned char)*s))
        s++;

    if (s[0] == '\0')
        return -1;

    val = strtoul(s, &endptr, 16);

    while (isspace((unsigned char)*endptr))
        endptr++;

    if (*endptr != '\0')
        return -1;

    *out = (u32)val;
    return 0;
}

static int parse_count(const char *s, u32 *out) {
    char *endptr;
    unsigned long val;

    if (s == NULL)
        return -1;

    while (isspace((unsigned char)*s))
        s++;

    if (s[0] == '\0')
        return -1;

    val = strtoul(s, &endptr, 0);

    while (isspace((unsigned char)*endptr))
        endptr++;

    if (*endptr != '\0')
        return -1;

    *out = (u32)val;
    return 0;
}

static int load_imem_from_uart(u32 offset, u32 count) {
    char line[128];

    if (offset > GPGPU_IMEM_ENTRIES || count > (GPGPU_IMEM_ENTRIES - offset)) {
        xil_printf("ERROR: IMEM load range offset=%u count=%u exceeds GPGPU_IMEM_ENTRIES=%d\r\n",
                   offset, count, GPGPU_IMEM_ENTRIES);
        return -1;
    }

    xil_printf("READY_FOR_BULK_IMEM\r\n");
    for (u32 i = 0; i < count; i++) {
        read_line(line, sizeof(line));
        trim(line);

        if (parse_u32_hex(line, &rx_buffer[i]) != 0) {
            xil_printf("ERROR_INVALID_HEX\r\n");
            return -1;
        }
    }

    for (u32 i = 0; i < count; i++) {
        if (gpgpu_write_imem(offset + i, rx_buffer[i]) != 0) {
            xil_printf("ERROR_AXI_WRITE\r\n");
            return -1;
        }
    }
    xil_printf("IMEM_LOAD_COMPLETE\r\n");

    return 0;
}

static int load_dmem_from_uart(u32 offset, u32 count) {
    char line[128];

    if (offset > GPGPU_DMEM_ENTRIES || count > (GPGPU_DMEM_ENTRIES - offset)) {
        xil_printf("ERROR: DMEM load range offset=%u count=%u exceeds GPGPU_DMEM_ENTRIES=%d\r\n",
                   offset, count, GPGPU_DMEM_ENTRIES);
        return -1;
    }

    xil_printf("Paste %u DMEM words as ASCII hex, one per line.\r\n", count);

    xil_printf("READY_FOR_BULK_DMEM\r\n");
    for (u32 i = 0; i < count; i++) {
        read_line(line, sizeof(line));
        trim(line);

        if (parse_u32_hex(line, &rx_buffer[i]) != 0) {
            xil_printf("ERROR_INVALID_HEX\r\n");
            return -1;
        }
    }

    for (u32 i = 0; i < count; i++) {
        if (gpgpu_write_dmem(offset + i, rx_buffer[i]) != 0) {
            xil_printf("ERROR_AXI_WRITE\r\n");
            return -1;
        }
    }
    xil_printf("DMEM_LOAD_COMPLETE\r\n");

    return 0;
}

static int load_imem_binary(u32 offset, u32 count) {
    if (offset > GPGPU_IMEM_ENTRIES || count > (GPGPU_IMEM_ENTRIES - offset)) {
        xil_printf("ERROR: IMEM binary load range offset=%u count=%u exceeds GPGPU_IMEM_ENTRIES=%d\n",
                   offset, count, GPGPU_IMEM_ENTRIES);
        return -1;
    }

    xil_printf("READY_IMEM_BIN\n");
    for (u32 i = 0; i < count; i++) {
        u32 val = 0;
        val |= ((u32)inbyte() & 0xFF) << 0;  // Byte 0 (LSB)
        val |= ((u32)inbyte() & 0xFF) << 8;  // Byte 1
        val |= ((u32)inbyte() & 0xFF) << 16; // Byte 2
        val |= ((u32)inbyte() & 0xFF) << 24; // Byte 3 (MSB)
        rx_buffer[i] = val;
    }

    for (u32 i = 0; i < count; i++) {
        gpgpu_write_imem(offset + i, rx_buffer[i]);
    }
    xil_printf("IMEM_LOAD_COMPLETE\n");
    return 0;
}

static int load_dmem_binary(u32 offset, u32 count) {
    if (offset > GPGPU_DMEM_ENTRIES || count > (GPGPU_DMEM_ENTRIES - offset)) {
        xil_printf("ERROR: DMEM binary load range offset=%u count=%u exceeds GPGPU_DMEM_ENTRIES=%d\n",
                   offset, count, GPGPU_DMEM_ENTRIES);
        return -1;
    }

    xil_printf("READY_DMEM_BIN\n");
    for (u32 i = 0; i < count; i++) {
        u32 val = 0;
        val |= ((u32)inbyte() & 0xFF) << 0;
        val |= ((u32)inbyte() & 0xFF) << 8;
        val |= ((u32)inbyte() & 0xFF) << 16;
        val |= ((u32)inbyte() & 0xFF) << 24;
        rx_buffer[i] = val;
    }

    for (u32 i = 0; i < count; i++) {
        gpgpu_write_dmem(offset + i, rx_buffer[i]);
    }
    
    xil_printf("DMEM_LOAD_COMPLETE\n");
    return 0;
}

static int gpgpu_dump_dmem_binary(u32 offset, u32 count) {
    if (offset > GPGPU_DMEM_ENTRIES || count > (GPGPU_DMEM_ENTRIES - offset)) {
        xil_printf("ERROR: DMEM binary dump range offset=%u count=%u exceeds GPGPU_DMEM_ENTRIES=%d\n",
                   offset, count, GPGPU_DMEM_ENTRIES);
        return -1;
    }

    xil_printf("BEGIN_DMEM_BIN\n");

    for (u32 i = 0; i < count; i++) {
        u32 val;
        gpgpu_read_dmem(offset + i, &val);

        outbyte((val >> 0)  & 0xFF);
        outbyte((val >> 8)  & 0xFF);
        outbyte((val >> 16) & 0xFF);
        outbyte((val >> 24) & 0xFF);
    }

    xil_printf("\r\n");
    
    return 0;
}

static void print_help(void) {
    xil_printf("\r\nCommands:\r\n");
    xil_printf("  --------- GENERAL ---------\r\n");
    xil_printf("  help\r\n");
    xil_printf("  status\r\n");
    xil_printf("  wimem <addr_hex> <word_hex>\r\n");
    xil_printf("  wdmem <addr_hex> <word_hex>\r\n");
    xil_printf("  rimem <addr_hex>\r\n");
    xil_printf("  rdmem <addr_hex>\r\n");
    xil_printf("  --------- DUMPING ---------\r\n");
    xil_printf("  dumpimem <offset> <count>\r\n");
    xil_printf("  dumpdmem <offset> <count>\r\n");
    xil_printf("  dumpdmem_bin <offset> <count>\r\n");
    xil_printf("  --------- LOADING ---------\r\n");
    xil_printf("  loadimem <offset> <count>\r\n");
    xil_printf("  loaddmem <offset> <count>\r\n");
    xil_printf("  loadimem_bin <offset> <count>\r\n");
    xil_printf("  loaddmem_bin <offset> <count>\r\n");
    xil_printf("  --------- CONTROL ---------\r\n");
    xil_printf("  run\r\n");
    xil_printf("  bench <frames>   (run the kernel back to back, report frames/s and the perf counters)\r\n");
    xil_printf("  clear   (acknowledge STOPPED/FAULTED)\r\n");
    xil_printf("  reset   (PL reset; needed after a fatal fault)\r\n");
    xil_printf("  --------- DISPLAY ---------\r\n");
    xil_printf("  display <fb>   (show framebuffer 0 or 1 on HDMI)\r\n");
    xil_printf("\r\n");
}

int main(void) {
    char line[128];
    xil_printf("\r\nGPGPU UART Host Monitor\r\n");

    if (gpgpu_init() != 0) {
        xil_printf("ERROR: GPGPU initialization failed\r\n");
        return 1;
    }

    gpgpu_print_status();
    display_start(shown_fb);
#if GPGPU_AUTORUN
    autorun();
#endif
    print_help();

    while (1) {
        char *cmd;
        char *arg1;
        char *arg2;

        xil_printf("gpgpu> ");
        read_line(line, sizeof(line));
        trim(line);

        cmd = strtok(line, " \t");
        if (cmd == NULL)
            continue;

        if (strcmp(cmd, "help") == 0) {
            print_help();

        } else if (strcmp(cmd, "status") == 0) {
            gpgpu_print_status();

        } else if (strcmp(cmd, "wimem") == 0) {
            u32 addr, word;

            arg1 = strtok(NULL, " \t");
            arg2 = strtok(NULL, " \t");

            if (!arg1 || !arg2 ||
                parse_u32_hex(arg1, &addr) != 0 ||
                parse_u32_hex(arg2, &word) != 0) {
                xil_printf("Usage: wimem <addr_hex> <word_hex>\r\n");
                continue;
            }

            gpgpu_write_imem(addr, word);

        } else if (strcmp(cmd, "wdmem") == 0) {
            u32 addr, word;

            arg1 = strtok(NULL, " \t");
            arg2 = strtok(NULL, " \t");

            if (!arg1 || !arg2 ||
                parse_u32_hex(arg1, &addr) != 0 ||
                parse_u32_hex(arg2, &word) != 0) {
                xil_printf("Usage: wdmem <addr_hex> <word_hex>\r\n");
                continue;
            }

            gpgpu_write_dmem(addr, word);

        } else if (strcmp(cmd, "rimem") == 0) {
            u32 addr, data;

            arg1 = strtok(NULL, " \t");

            if (!arg1 || parse_u32_hex(arg1, &addr) != 0) {
                xil_printf("Usage: rimem <addr_hex>\r\n");
                continue;
            }

            if (gpgpu_read_imem(addr, &data) == 0)
                xil_printf("IMEM[%u] = 0x%08x\r\n", addr, data);

        } else if (strcmp(cmd, "rdmem") == 0) {
            u32 addr, data;

            arg1 = strtok(NULL, " \t");

            if (!arg1 || parse_u32_hex(arg1, &addr) != 0) {
                xil_printf("Usage: rdmem <addr_hex>\r\n");
                continue;
            }

            if (gpgpu_read_dmem(addr, &data) == 0)
                xil_printf("DMEM[%u] = 0x%08x\r\n", addr, data);

        } else if (strcmp(cmd, "dumpimem") == 0) {
            u32 offset, count;

            arg1 = strtok(NULL, " \t");
            arg2 = strtok(NULL, " \t");
            if (parse_count(arg1, &offset) != 0 || parse_count(arg2, &count) != 0) {
                xil_printf("Usage: dumpimem <offset> <count>\r\n");
                continue;
            }

            gpgpu_dump_imem_ascii(offset, count);

        } else if (strcmp(cmd, "dumpdmem") == 0) {
            u32 offset, count;

            arg1 = strtok(NULL, " \t");
            arg2 = strtok(NULL, " \t");
            if (parse_count(arg1, &offset) != 0 || parse_count(arg2, &count) != 0) {
                xil_printf("Usage: dumpdmem <offset> <count>\r\n");
                continue;
            }

            gpgpu_dump_dmem_ascii(offset, count);

        }  else if (strcmp(cmd, "dumpdmem_bin") == 0) {
            u32 offset, count;

            arg1 = strtok(NULL, " \t");
            arg2 = strtok(NULL, " \t");
            if (parse_count(arg1, &offset) != 0 || parse_count(arg2, &count) != 0) {
                xil_printf("Usage: dumpdmem_bin <offset> <count>\r\n");
                continue;
            }

            gpgpu_dump_dmem_binary(offset, count);

        } else if (strcmp(cmd, "loadimem") == 0) {
            u32 offset, count;

            arg1 = strtok(NULL, " \t");
            arg2 = strtok(NULL, " \t");
            if (parse_count(arg1, &offset) != 0 || parse_count(arg2, &count) != 0) {
                xil_printf("Usage: loadimem <offset> <count>\r\n");
                continue;
            }

            load_imem_from_uart(offset, count);

        } else if (strcmp(cmd, "loaddmem") == 0) {
            u32 offset, count;

            arg1 = strtok(NULL, " \t");
            arg2 = strtok(NULL, " \t");
            if (parse_count(arg1, &offset) != 0 || parse_count(arg2, &count) != 0) {
                xil_printf("Usage: loaddmem <offset> <count>\r\n");
                continue;
            }

            load_dmem_from_uart(offset, count);

        }  else if (strcmp(cmd, "loadimem_bin") == 0) {
            u32 offset, count;

            arg1 = strtok(NULL, " \t");
            arg2 = strtok(NULL, " \t");
            if (parse_count(arg1, &offset) != 0 || parse_count(arg2, &count) != 0) {
                xil_printf("Usage: loadimem_bin <offset> <count>\r\n");
                continue;
            }

            load_imem_binary(offset, count);

        } else if (strcmp(cmd, "loaddmem_bin") == 0) {
            u32 offset, count;

            arg1 = strtok(NULL, " \t");
            arg2 = strtok(NULL, " \t");
            if (parse_count(arg1, &offset) != 0 || parse_count(arg2, &count) != 0) {
                xil_printf("Usage: loaddmem_bin <offset> <count>\r\n");
                continue;
            }

            load_dmem_binary(offset, count);

        } else if (strcmp(cmd, "run") == 0) {
            gpgpu_start_and_wait();

        } else if (strcmp(cmd, "bench") == 0) {
            u32 frames;

            arg1 = strtok(NULL, " \t");
            if (parse_count(arg1, &frames) != 0) {
                xil_printf("Usage: bench <frames>\r\n");
                continue;
            }

            bench(frames);

        } else if (strcmp(cmd, "clear") == 0) {
            gpgpu_clear();
            xil_printf("Acknowledged the STOPPED and FAULTED latches (a fatal fault needs `reset`).\r\n");
            gpgpu_print_status();

        } else if (strcmp(cmd, "reset") == 0) {
            /* The PL reset also resets the VDMA: stop it first. */
            display_stop();
            if (gpgpu_reset() != GPGPU_OK)
                xil_printf("ERROR: GPGPU initialization after reset failed\r\n");
            gpgpu_print_status();
            display_start(shown_fb);

        } else if (strcmp(cmd, "display") == 0) {
            u32 fb;

            arg1 = strtok(NULL, " \t");
            if (parse_count(arg1, &fb) != 0) {
                xil_printf("Usage: display <fb>\r\n");
                continue;
            }

            display_show(fb);

        } else {
            xil_printf("Unknown command: %s\r\n", cmd);
            xil_printf("Type 'help'\r\n");
        }
    }

    return 0;
}