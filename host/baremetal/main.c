#include "xil_io.h"
#include "xil_printf.h"
#include "xparameters.h"
#include "xil_types.h"

#include <stdlib.h>
#include <string.h>
#include <ctype.h>

#define CMD_IMEM_WRITE 0
#define CMD_WRITE_DONE 1
#define CMD_DMEM_READ  2
#define CMD_REG_READ   3
#define CMD_READ_DONE  4

#define VALID_BIT      (1 << 3)

// status[0] = loading
// status[1] = running
// status[2] = dumping
// status[3] = busy
// status[4] = done
#define STATUS_LOADING (1 << 0)
#define STATUS_RUNNING (1 << 1)
#define STATUS_DUMPING (1 << 2)
#define STATUS_BUSY    (1 << 3)
#define STATUS_DONE    (1 << 4)

#define GPIO_CMD_BASE     XPAR_AXI_GPIO_CMD_BASEADDR
#define GPIO_ADDRESS_BASE XPAR_AXI_GPIO_ADDRESS_BASEADDR
#define GPIO_WDATA_BASE   XPAR_AXI_GPIO_WDATA_BASEADDR
#define GPIO_RDATA_BASE   XPAR_AXI_GPIO_RDATA_BASEADDR
#define GPIO_STATUS_BASE  XPAR_AXI_GPIO_STATUS_BASEADDR

#define IMEM_WORDS 1024
#define DMEM_WORDS 1024
#define REG_WORDS  32

#define TIMEOUT_COUNT 100000000

// Some BSPs provide inbyte() without a visible prototype.
extern char inbyte(void);

static inline void gpio_write(u32 base, u32 value) {
    Xil_Out32(base, value);
}

static inline u32 gpio_read(u32 base) {
    return Xil_In32(base);
}

static u32 read_status(void) {
    return gpio_read(GPIO_STATUS_BASE);
}

static void print_status(void) {
    u32 s = read_status();

    xil_printf("STATUS = 0x%08lx\r\n", s);
    xil_printf("  loading = %lu\r\n", (s & STATUS_LOADING) ? 1UL : 0UL);
    xil_printf("  running = %lu\r\n", (s & STATUS_RUNNING) ? 1UL : 0UL);
    xil_printf("  dumping = %lu\r\n", (s & STATUS_DUMPING) ? 1UL : 0UL);
    xil_printf("  busy    = %lu\r\n", (s & STATUS_BUSY) ? 1UL : 0UL);
    xil_printf("  done    = %lu\r\n", (s & STATUS_DONE) ? 1UL : 0UL);
}

static int wait_until_not_busy(u32 timeout) {
    while (timeout--) {
        if ((read_status() & STATUS_BUSY) == 0)
            return 0;
    }

    return -1;
}

static int wait_until_done(u32 timeout) {
    while (timeout--) {
        if (read_status() & STATUS_DONE)
            return 0;
    }

    return -1;
}

static int wait_until_done_cleared(u32 timeout) {
    while (timeout--) {
        if ((read_status() & STATUS_DONE) == 0)
            return 0;
    }

    return -1;
}

static int wait_until_dumping(u32 timeout) {
    while (timeout--) {
        if (read_status() & STATUS_DUMPING)
            return 0;
    }

    return -1;
}

static int begin_command(u32 cmd, u32 addr, u32 wdata) {
    if (wait_until_not_busy(TIMEOUT_COUNT) != 0) {
        xil_printf("ERROR: timeout waiting for busy=0 before cmd %lu\r\n", cmd);
        print_status();
        return -1;
    }

    gpio_write(GPIO_ADDRESS_BASE, addr);
    gpio_write(GPIO_WDATA_BASE, wdata);

    // Keep valid high until done is observed.
    gpio_write(GPIO_CMD_BASE, cmd | VALID_BIT);

    if (wait_until_done(TIMEOUT_COUNT) != 0) {
        xil_printf("ERROR: timeout waiting for done=1 after cmd %lu\r\n", cmd);
        print_status();
        return -1;
    }

    return 0;
}

static int end_command(u32 cmd) {
    // Drop valid.
    gpio_write(GPIO_CMD_BASE, cmd);

    if (wait_until_done_cleared(TIMEOUT_COUNT) != 0) {
        xil_printf("ERROR: timeout waiting for done=0 after cmd %lu\r\n", cmd);
        print_status();
        return -1;
    }

    return 0;
}

static int send_command(u32 cmd, u32 addr, u32 wdata) {
    if (begin_command(cmd, addr, wdata) != 0)
        return -1;

    return end_command(cmd);
}

static int write_imem(u32 addr, u32 instr) {
    return send_command(CMD_IMEM_WRITE, addr, instr);
}

static int read_dmem(u32 addr, u32 *data) {
    if (begin_command(CMD_DMEM_READ, addr, 0) != 0)
        return -1;

    // Read while done is high. The hardware should be holding rdata stable.
    *data = gpio_read(GPIO_RDATA_BASE);

    return end_command(CMD_DMEM_READ);
}

static int read_regfile(u32 addr, u32 *data) {
    if (begin_command(CMD_REG_READ, addr, 0) != 0)
        return -1;

    *data = gpio_read(GPIO_RDATA_BASE);

    return end_command(CMD_REG_READ);
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

static int load_imem_from_uart(u32 count) {
    char line[128];
    u32 instr;

    if (count > IMEM_WORDS) {
        xil_printf("ERROR: count %lu exceeds IMEM_WORDS=%d\r\n", count, IMEM_WORDS);
        return -1;
    }

    xil_printf("Paste %lu instruction words as ASCII hex, one per line.\r\n", count);
    xil_printf("Example: 00000013\r\n");

    for (u32 i = 0; i < count; i++) {
        while (1) {
            xil_printf("IMEM[%lu] > ", i);
            read_line(line, sizeof(line));
            trim(line);

            if (parse_u32_hex(line, &instr) == 0)
                break;

            xil_printf("Invalid hex word. Try again.\r\n");
        }

        if (write_imem(i, instr) != 0) {
            xil_printf("ERROR: failed writing IMEM[%lu]\r\n", i);
            return -1;
        }

        xil_printf("  wrote IMEM[%lu] = 0x%08lx\r\n", i, instr);
    }

    xil_printf("IMEM load complete.\r\n");
    return 0;
}

static int start_core_and_wait(void) {
    xil_printf("Starting core...\r\n");

    if (send_command(CMD_WRITE_DONE, 0, 0) != 0) {
        xil_printf("ERROR: WRITE_DONE failed.\r\n");
        return -1;
    }

    xil_printf("Waiting for dumping state...\r\n");

    if (wait_until_dumping(TIMEOUT_COUNT) != 0) {
        xil_printf("ERROR: timeout waiting for dumping state.\r\n");
        print_status();
        return -1;
    }

    xil_printf("Core entered dumping state.\r\n");
    return 0;
}

static int dump_dmem_ascii(void) {
    u32 data;

    xil_printf("BEGIN_DMEM_DUMP\r\n");

    for (u32 i = 0; i < DMEM_WORDS; i++) {
        if (read_dmem(i, &data) != 0) {
            xil_printf("ERROR: failed reading DMEM[%lu]\r\n", i);
            return -1;
        }

        xil_printf("%04lu: %08lx\r\n", i, data);
    }

    xil_printf("END_DMEM_DUMP\r\n");
    return 0;
}

static int dump_regfile_ascii(void) {
    u32 data;

    xil_printf("BEGIN_REG_DUMP\r\n");

    for (u32 i = 0; i < REG_WORDS; i++) {
        if (read_regfile(i, &data) != 0) {
            xil_printf("ERROR: failed reading REG[%lu]\r\n", i);
            return -1;
        }

        xil_printf("x%02lu: %08lx\r\n", i, data);
    }

    xil_printf("END_REG_DUMP\r\n");
    return 0;
}

static int finish_readback(void) {
    xil_printf("Sending READ_DONE...\r\n");

    if (send_command(CMD_READ_DONE, 0, 0) != 0) {
        xil_printf("ERROR: READ_DONE failed.\r\n");
        return -1;
    }

    xil_printf("Returned to loading state.\r\n");
    return 0;
}

static int auto_run_from_uart(u32 count) {
    if (load_imem_from_uart(count) != 0)
        return -1;

    if (start_core_and_wait() != 0)
        return -1;

    if (dump_dmem_ascii() != 0)
        return -1;

    if (dump_regfile_ascii() != 0)
        return -1;

    if (finish_readback() != 0)
        return -1;

    return 0;
}

static void print_help(void) {
    xil_printf("\r\nCommands:\r\n");
    xil_printf("  help\r\n");
    xil_printf("  status\r\n");
    xil_printf("  load <count_hex_or_dec>\r\n");
    xil_printf("  run\r\n");
    xil_printf("  dump\r\n");
    xil_printf("  done\r\n");
    xil_printf("  auto <count_hex_or_dec>\r\n");
    xil_printf("  imem <addr_hex> <instr_hex>\r\n");
    xil_printf("  dmem <addr_hex>\r\n");
    xil_printf("  reg <addr_hex>\r\n");
    xil_printf("\r\nTypical use:\r\n");
    xil_printf("  auto 3\r\n");
    xil_printf("  00000013\r\n");
    xil_printf("  00000013\r\n");
    xil_printf("  00008067\r\n");
    xil_printf("\r\n");
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

    // strtoul with base 0 accepts decimal, 0x-prefixed hex, and octal.
    val = strtoul(s, &endptr, 0);

    while (isspace((unsigned char)*endptr))
        endptr++;

    if (*endptr != '\0')
        return -1;

    *out = (u32)val;
    return 0;
}

int main(void) {
    char line[128];

    xil_printf("\r\nGPGPU UART Host Monitor\r\n");

    gpio_write(GPIO_CMD_BASE, 0);
    gpio_write(GPIO_ADDRESS_BASE, 0);
    gpio_write(GPIO_WDATA_BASE, 0);

    print_status();
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
            print_status();

        } else if (strcmp(cmd, "load") == 0) {
            u32 count;

            arg1 = strtok(NULL, " \t");
            if (parse_count(arg1, &count) != 0) {
                xil_printf("Usage: load <count>\r\n");
                continue;
            }

            load_imem_from_uart(count);

        } else if (strcmp(cmd, "run") == 0) {
            start_core_and_wait();

        } else if (strcmp(cmd, "dump") == 0) {
            dump_dmem_ascii();
            dump_regfile_ascii();

        } else if (strcmp(cmd, "done") == 0) {
            finish_readback();

        } else if (strcmp(cmd, "auto") == 0) {
            u32 count;

            arg1 = strtok(NULL, " \t");
            if (parse_count(arg1, &count) != 0) {
                xil_printf("Usage: auto <count>\r\n");
                continue;
            }

            auto_run_from_uart(count);

        } else if (strcmp(cmd, "imem") == 0) {
            u32 addr;
            u32 instr;

            arg1 = strtok(NULL, " \t");
            arg2 = strtok(NULL, " \t");

            if (!arg1 || !arg2 ||
                parse_u32_hex(arg1, &addr) != 0 ||
                parse_u32_hex(arg2, &instr) != 0) {
                xil_printf("Usage: imem <addr_hex> <instr_hex>\r\n");
                continue;
            }

            if (write_imem(addr, instr) == 0)
                xil_printf("IMEM[%lu] = 0x%08lx written\r\n", addr, instr);

        } else if (strcmp(cmd, "dmem") == 0) {
            u32 addr;
            u32 data;

            arg1 = strtok(NULL, " \t");

            if (!arg1 || parse_u32_hex(arg1, &addr) != 0) {
                xil_printf("Usage: dmem <addr_hex>\r\n");
                continue;
            }

            if (read_dmem(addr, &data) == 0)
                xil_printf("DMEM[%lu] = 0x%08lx\r\n", addr, data);

        } else if (strcmp(cmd, "reg") == 0) {
            u32 addr;
            u32 data;

            arg1 = strtok(NULL, " \t");

            if (!arg1 || parse_u32_hex(arg1, &addr) != 0) {
                xil_printf("Usage: reg <addr_hex>\r\n");
                continue;
            }

            if (read_regfile(addr, &data) == 0)
                xil_printf("REG[%lu] = 0x%08lx\r\n", addr, data);

        } else {
            xil_printf("Unknown command: %s\r\n", cmd);
            xil_printf("Type 'help' for commands.\r\n");
        }
    }

    return 0;
}