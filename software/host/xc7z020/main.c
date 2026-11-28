#include "gpgpu_driver.h"
#include "gpgpu_display.h"
#include "gpgpu_loader.h"

#include "xparameters.h"
#include "xil_cache.h"
#include "xil_io.h"
#include "xil_printf.h"
#include "xil_types.h"
#include "xiltimer.h"
#include "xcortexa9_config.h"
#include "xuartps_hw.h"
#include "sleep.h"

#include <stdlib.h>
#include <string.h>
#include <ctype.h>

extern char inbyte(void);

/* DDR test picture: `gmemfill` writes a picture into GMEM (the GPU's
 * read-write DDR region) and clears a framebuffer, a loaded program's kernel
 * copies GMEM -> framebuffer, and `gmemcheck` compares the two word by word. The GPU reaches DDR through an HP port that does not snoop
 * the A9 caches: the A9 flushes what it writes before the GPU reads it, and
 * invalidates what the GPU wrote before reading it. */
#define GMEMTEST_WORDS            (GPGPU_FB_WIDTH * GPGPU_FB_HEIGHT)
#define GMEMTEST_BYTES            (GMEMTEST_WORDS * 4U)
#define GMEMTEST_REPORT_MAX       8U

_Static_assert(GMEMTEST_BYTES <= GPGPU_GMEM_SIZE, "the test picture does not fit GMEM");

/* Pixel (x, y) of the test picture: a red/green gradient whose low bits sit
 * in blue, so every pixel of the frame has its own value and a word that
 * lands in the wrong place cannot match by accident. */
static inline u32 gmemtest_pixel(u32 x, u32 y) {
    return ((x >> 3) << 16) | ((y >> 2) << 8) | ((x & 7U) << 5) | ((y & 3U) << 3);
}

static void gmemfill(u32 fb) {
    u32 *gmem = (u32 *)(UINTPTR)GPGPU_GMEM_BASE;
    u32 *dst = (u32 *)(UINTPTR)gpgpu_display_address(fb);

    for (u32 y = 0U; y < GPGPU_FB_HEIGHT; y++)
        for (u32 x = 0U; x < GPGPU_FB_WIDTH; x++)
            gmem[y * GPGPU_FB_WIDTH + x] = gmemtest_pixel(x, y);
    memset(dst, 0, GMEMTEST_BYTES);

    Xil_DCacheFlushRange((INTPTR)gmem, GMEMTEST_BYTES);
    Xil_DCacheFlushRange((INTPTR)dst, GMEMTEST_BYTES);
    xil_printf("GMEMFILL_DONE %u words at 0x%08x, FB%u cleared\r\n",
               (u32)GMEMTEST_WORDS, (u32)GPGPU_GMEM_BASE, fb);
}

static void gmemcheck(u32 fb) {
    const u32 *gmem = (const u32 *)(UINTPTR)GPGPU_GMEM_BASE;
    const u32 *dst = (const u32 *)(UINTPTR)gpgpu_display_address(fb);
    u32 mismatches = 0U;

    Xil_DCacheInvalidateRange((INTPTR)dst, GMEMTEST_BYTES);
    for (u32 i = 0U; i < GMEMTEST_WORDS; i++) {
        if (dst[i] == gmem[i])
            continue;
        if (mismatches < GMEMTEST_REPORT_MAX)
            xil_printf("  word %u (x %u, y %u): FB%u 0x%08x, GMEM 0x%08x\r\n", i,
                       i % GPGPU_FB_WIDTH, i / GPGPU_FB_WIDTH, fb, dst[i], gmem[i]);
        mismatches++;
    }

    if (mismatches == 0U)
        xil_printf("GMEMCHECK_PASS %u words\r\n", (u32)GMEMTEST_WORDS);
    else
        xil_printf("GMEMCHECK_FAIL %u of %u words differ\r\n", mismatches, (u32)GMEMTEST_WORDS);
}

/* GMEM: the GPU's read-write DDR region, which holds a program's .rodata, .data
 * and .bss (software/programs/linker.ld) and its buffers. Offsets and counts
 * are words from GPGPU_GMEM_BASE. The A9 writes it through its cache, so
 * every write is flushed before the GPU runs, and a read invalidates first:
 * the GPU's HP port does not snoop the caches. */
#define GMEM_WORDS (GPGPU_GMEM_SIZE / 4U)

static volatile u32 *gmem_words(void) {
    return (volatile u32 *)(UINTPTR)GPGPU_GMEM_BASE;
}

static int gmem_span_ok(const char *what, u32 offset, u32 count) {
    if (offset > GMEM_WORDS || count > (GMEM_WORDS - offset)) {
        xil_printf("ERROR: GMEM %s range offset=%u count=%u exceeds %u words\r\n", what, offset, count, GMEM_WORDS);
        return 0;
    }
    return 1;
}

static int dump_gmem_binary(u32 offset, u32 count) {
    volatile u32 *gmem = gmem_words();

    if (!gmem_span_ok("binary dump", offset, count))
        return -1;

    Xil_DCacheInvalidateRange((INTPTR)(GPGPU_GMEM_BASE + 4U * offset), 4U * count);
    xil_printf("BEGIN_GMEM_BIN\n");
    for (u32 i = 0; i < count; i++) {
        u32 val = gmem[offset + i];

        outbyte((val >> 0)  & 0xFF);
        outbyte((val >> 8)  & 0xFF);
        outbyte((val >> 16) & 0xFF);
        outbyte((val >> 24) & 0xFF);
    }
    xil_printf("\r\n");
    return 0;
}

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

static int gpgpu_dump_smem_binary(u32 offset, u32 count) {
    if (offset > GPGPU_SMEM_ENTRIES || count > (GPGPU_SMEM_ENTRIES - offset)) {
        xil_printf("ERROR: SMEM binary dump range offset=%u count=%u exceeds GPGPU_SMEM_ENTRIES=%d\n",
                   offset, count, GPGPU_SMEM_ENTRIES);
        return -1;
    }

    xil_printf("BEGIN_SMEM_BIN\n");

    for (u32 i = 0; i < count; i++) {
        u32 val;
        gpgpu_read_smem(offset + i, &val);

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
    xil_printf("  wsmem <addr_hex> <word_hex>\r\n");
    xil_printf("  rimem <addr_hex>\r\n");
    xil_printf("  rsmem <addr_hex>\r\n");
    xil_printf("  --------- DUMPING ---------\r\n");
    xil_printf("  dumpimem <offset> <count>\r\n");
    xil_printf("  dumpsmem <offset> <count>\r\n");
    xil_printf("  dumpsmem_bin <offset> <count>\r\n");
    xil_printf("  dumpgmem_bin <offset> <count>   (word offsets from GMEM_BASE)\r\n");
    xil_printf("  --------- PROGRAMS (docs/runtime-spec.md) ---------\r\n");
    xil_printf("  load <entry_hex> <segments_hex>   (receive a program; `fpga programs:<p>:run` sends it)\r\n");
    xil_printf("  run <name> [arguments]   (run the loaded program; it returns here)\r\n");
    xil_printf("  --------- CONTROL ---------\r\n");
    xil_printf("  perf   (report the perf counters of the last kernel)\r\n");
    xil_printf("  clear   (acknowledge STOPPED/FAULTED)\r\n");
    xil_printf("  reset   (PL reset; needed after a fatal fault)\r\n");
    xil_printf("  --------- DISPLAY ---------\r\n");
    xil_printf("  display <fb>   (show framebuffer 0 or 1 on HDMI)\r\n");
    xil_printf("  --------- DDR TEST PICTURE ---------\r\n");
    xil_printf("  gmemfill <fb>   (write the test picture to GMEM, clear framebuffer fb)\r\n");
    xil_printf("  gmemcheck <fb>  (compare framebuffer fb with GMEM)\r\n");
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
    gpgpu_display_start(gpgpu_display_shown());
    print_help();

    while (1) {
        char *cmd;
        char *arg1;
        char *arg2;

        xil_printf("gpgpu> ");
        read_line(line, sizeof(line));
        trim(line);
        const size_t line_length = strlen(line); /* before strtok cuts it */

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

        } else if (strcmp(cmd, "wsmem") == 0) {
            u32 addr, word;

            arg1 = strtok(NULL, " \t");
            arg2 = strtok(NULL, " \t");

            if (!arg1 || !arg2 ||
                parse_u32_hex(arg1, &addr) != 0 ||
                parse_u32_hex(arg2, &word) != 0) {
                xil_printf("Usage: wsmem <addr_hex> <word_hex>\r\n");
                continue;
            }

            gpgpu_write_smem(addr, word);

        } else if (strcmp(cmd, "rimem") == 0) {
            u32 addr, data;

            arg1 = strtok(NULL, " \t");

            if (!arg1 || parse_u32_hex(arg1, &addr) != 0) {
                xil_printf("Usage: rimem <addr_hex>\r\n");
                continue;
            }

            if (gpgpu_read_imem(addr, &data) == 0)
                xil_printf("IMEM[%u] = 0x%08x\r\n", addr, data);

        } else if (strcmp(cmd, "rsmem") == 0) {
            u32 addr, data;

            arg1 = strtok(NULL, " \t");

            if (!arg1 || parse_u32_hex(arg1, &addr) != 0) {
                xil_printf("Usage: rsmem <addr_hex>\r\n");
                continue;
            }

            if (gpgpu_read_smem(addr, &data) == 0)
                xil_printf("SMEM[%u] = 0x%08x\r\n", addr, data);

        } else if (strcmp(cmd, "dumpimem") == 0) {
            u32 offset, count;

            arg1 = strtok(NULL, " \t");
            arg2 = strtok(NULL, " \t");
            if (parse_count(arg1, &offset) != 0 || parse_count(arg2, &count) != 0) {
                xil_printf("Usage: dumpimem <offset> <count>\r\n");
                continue;
            }

            gpgpu_dump_imem_ascii(offset, count);

        } else if (strcmp(cmd, "dumpsmem") == 0) {
            u32 offset, count;

            arg1 = strtok(NULL, " \t");
            arg2 = strtok(NULL, " \t");
            if (parse_count(arg1, &offset) != 0 || parse_count(arg2, &count) != 0) {
                xil_printf("Usage: dumpsmem <offset> <count>\r\n");
                continue;
            }

            gpgpu_dump_smem_ascii(offset, count);

        }  else if (strcmp(cmd, "dumpsmem_bin") == 0) {
            u32 offset, count;

            arg1 = strtok(NULL, " \t");
            arg2 = strtok(NULL, " \t");
            if (parse_count(arg1, &offset) != 0 || parse_count(arg2, &count) != 0) {
                xil_printf("Usage: dumpsmem_bin <offset> <count>\r\n");
                continue;
            }

            gpgpu_dump_smem_binary(offset, count);

        } else if (strcmp(cmd, "dumpgmem_bin") == 0) {
            u32 offset, count;

            arg1 = strtok(NULL, " \t");
            arg2 = strtok(NULL, " \t");
            if (parse_count(arg1, &offset) != 0 || parse_count(arg2, &count) != 0) {
                xil_printf("ERROR: usage: %s <offset> <count>\r\n", cmd);
                continue;
            }

            dump_gmem_binary(offset, count);

        } else if (strcmp(cmd, "load") == 0) {
            arg1 = strtok(NULL, " \t");
            arg2 = strtok(NULL, " \t");
            gpgpu_loader_load(arg1, arg2);

        } else if (strcmp(cmd, "run") == 0) {
            /* The rest of the line: the program's name and arguments. */
            size_t used = (size_t)(cmd - line) + strlen(cmd) + 1U;
            gpgpu_loader_run(used <= line_length ? cmd + strlen(cmd) + 1 : (char *)"");

        } else if (strcmp(cmd, "perf") == 0) {
            static gpgpu_perf_t last;

            /* The GPU clears the counters at START: these are the last run's. */
            if (gpgpu_perf_read(&last) == GPGPU_OK)
                gpgpu_perf_report(&last, 1U);

        } else if (strcmp(cmd, "clear") == 0) {
            gpgpu_clear();
            xil_printf("Acknowledged the STOPPED and FAULTED latches (a fatal fault needs `reset`).\r\n");
            gpgpu_print_status();

        } else if (strcmp(cmd, "reset") == 0) {
            /* The PL reset also resets the VDMA: stop it first. */
            gpgpu_display_stop();
            if (gpgpu_pl_reset() != GPGPU_OK)
                xil_printf("ERROR: GPGPU initialization after reset failed\r\n");
            gpgpu_print_status();
            gpgpu_display_start(gpgpu_display_shown());

        } else if (strcmp(cmd, "display") == 0) {
            u32 fb;

            arg1 = strtok(NULL, " \t");
            if (parse_count(arg1, &fb) != 0) {
                xil_printf("Usage: display <fb>\r\n");
                continue;
            }

            gpgpu_display_show(fb, 1);

        } else if (strcmp(cmd, "gmemfill") == 0 || strcmp(cmd, "gmemcheck") == 0) {
            u32 fb;

            arg1 = strtok(NULL, " \t");
            if (parse_count(arg1, &fb) != 0 || fb >= GPGPU_DISPLAY_FRAMEBUFFERS) {
                xil_printf("ERROR: usage: %s <fb>, fb 0..%u\r\n", cmd, GPGPU_DISPLAY_FRAMEBUFFERS - 1U);
                continue;
            }

            if (strcmp(cmd, "gmemfill") == 0)
                gmemfill(fb);
            else
                gmemcheck(fb);

        } else {
            xil_printf("Unknown command: %s\r\n", cmd);
            xil_printf("Type 'help'\r\n");
        }
    }

    return 0;
}