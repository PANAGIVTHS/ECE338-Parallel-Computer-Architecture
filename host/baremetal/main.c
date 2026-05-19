#include "gpgpu_host.h"

#include "xil_printf.h"
#include "xil_types.h"

#include <stdlib.h>
#include <string.h>
#include <ctype.h>

extern char inbyte(void);

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

static int load_imem_from_uart(u32 count) {
    char line[128];
    u32 word;

    if (count > IMEM_WORDS) {
        xil_printf("ERROR: count %lu exceeds IMEM_WORDS=%d\r\n", count, IMEM_WORDS);
        return -1;
    }

    xil_printf("Paste %lu IMEM words as ASCII hex, one per line.\r\n", count);

    for (u32 i = 0; i < count; i++) {
        while (1) {
            xil_printf("IMEM[%lu] > ", i);
            read_line(line, sizeof(line));
            trim(line);

            if (parse_u32_hex(line, &word) == 0)
                break;

            xil_printf("Invalid hex word. Try again.\r\n");
        }

        if (gpgpu_write_imem(i, word) != 0)
            return -1;

        xil_printf("  wrote IMEM[%lu] = 0x%08lx\r\n", i, word);
    }

    return 0;
}

static int load_dmem_from_uart(u32 count) {
    char line[128];
    u32 word;

    if (count > DMEM_WORDS) {
        xil_printf("ERROR: count %lu exceeds DMEM_WORDS=%d\r\n", count, DMEM_WORDS);
        return -1;
    }

    xil_printf("Paste %lu DMEM words as ASCII hex, one per line.\r\n", count);

    for (u32 i = 0; i < count; i++) {
        while (1) {
            xil_printf("DMEM[%lu] > ", i);
            read_line(line, sizeof(line));
            trim(line);

            if (parse_u32_hex(line, &word) == 0)
                break;

            xil_printf("Invalid hex word. Try again.\r\n");
        }

        if (gpgpu_write_dmem(i, word) != 0)
            return -1;

        xil_printf("  wrote DMEM[%lu] = 0x%08lx\r\n", i, word);
    }

    return 0;
}

static void print_help(void) {
    xil_printf("\r\nCommands:\r\n");
    xil_printf("  help\r\n");
    xil_printf("  status\r\n");
    xil_printf("  wimem <addr_hex> <word_hex>\r\n");
    xil_printf("  wdmem <addr_hex> <word_hex>\r\n");
    xil_printf("  rimem <addr_hex>\r\n");
    xil_printf("  rdmem <addr_hex>\r\n");
    xil_printf("  dumpimem <count>\r\n");
    xil_printf("  dumpdmem <count>\r\n");
    xil_printf("  loadimem <count>\r\n");
    xil_printf("  loaddmem <count>\r\n");
    xil_printf("  run\r\n");
    xil_printf("  done\r\n");
    xil_printf("\r\n");
}

int main(void) {
    char line[128];

    xil_printf("\r\nGPGPU UART Host Monitor\r\n");

    gpgpu_init();
    gpgpu_print_status();
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
                xil_printf("IMEM[%lu] = 0x%08lx\r\n", addr, data);

        } else if (strcmp(cmd, "rdmem") == 0) {
            u32 addr, data;

            arg1 = strtok(NULL, " \t");

            if (!arg1 || parse_u32_hex(arg1, &addr) != 0) {
                xil_printf("Usage: rdmem <addr_hex>\r\n");
                continue;
            }

            if (gpgpu_read_dmem(addr, &data) == 0)
                xil_printf("DMEM[%lu] = 0x%08lx\r\n", addr, data);

        } else if (strcmp(cmd, "dumpimem") == 0) {
            u32 count;

            arg1 = strtok(NULL, " \t");
            if (parse_count(arg1, &count) != 0) {
                xil_printf("Usage: dumpimem <count>\r\n");
                continue;
            }

            gpgpu_dump_imem_ascii(count);

        } else if (strcmp(cmd, "dumpdmem") == 0) {
            u32 count;

            arg1 = strtok(NULL, " \t");
            if (parse_count(arg1, &count) != 0) {
                xil_printf("Usage: dumpdmem <count>\r\n");
                continue;
            }

            gpgpu_dump_dmem_ascii(count);

        } else if (strcmp(cmd, "loadimem") == 0) {
            u32 count;

            arg1 = strtok(NULL, " \t");
            if (parse_count(arg1, &count) != 0) {
                xil_printf("Usage: loadimem <count>\r\n");
                continue;
            }

            load_imem_from_uart(count);

        } else if (strcmp(cmd, "loaddmem") == 0) {
            u32 count;

            arg1 = strtok(NULL, " \t");
            if (parse_count(arg1, &count) != 0) {
                xil_printf("Usage: loaddmem <count>\r\n");
                continue;
            }

            load_dmem_from_uart(count);

        } else if (strcmp(cmd, "run") == 0) {
            gpgpu_start_and_wait();

        } else if (strcmp(cmd, "done") == 0) {
            gpgpu_finish_readback();

        } else {
            xil_printf("Unknown command: %s\r\n", cmd);
            xil_printf("Type 'help'\r\n");
        }
    }

    return 0;
}