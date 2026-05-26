#include "gpgpu_host.h"

#include "xil_io.h"
#include "xil_printf.h"
#include "xparameters.h"

#define CMD_IMEM_WRITE 0
#define CMD_DMEM_WRITE 1
#define CMD_WRITE_DONE 2
#define CMD_DMEM_READ  3
#define CMD_IMEM_READ  4
#define CMD_REG_READ   5
#define CMD_READ_DONE  6

#define VALID_BIT      (1 << 3)

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

#define TIMEOUT_COUNT 100000000

static inline void gpio_write(u32 base, u32 value) {
    Xil_Out32(base, value);
}

static inline u32 gpio_read(u32 base) {
    return Xil_In32(base);
}

u32 gpgpu_read_status(void) {
    return gpio_read(GPIO_STATUS_BASE);
}

void gpgpu_print_status(void) {
    u32 s = gpgpu_read_status();

    xil_printf("STATUS = 0x%08x\r\n", s);
    xil_printf("  loading = %u\r\n", (s & STATUS_LOADING) ? 1UL : 0UL);
    xil_printf("  running = %u\r\n", (s & STATUS_RUNNING) ? 1UL : 0UL);
    xil_printf("  dumping = %u\r\n", (s & STATUS_DUMPING) ? 1UL : 0UL);
    xil_printf("  busy    = %u\r\n", (s & STATUS_BUSY) ? 1UL : 0UL);
    xil_printf("  done    = %u\r\n", (s & STATUS_DONE) ? 1UL : 0UL);
}

int gpgpu_init(void) {
    gpio_write(GPIO_CMD_BASE, 0);
    gpio_write(GPIO_ADDRESS_BASE, 0);
    gpio_write(GPIO_WDATA_BASE, 0);
    return 0;
}

static int is_running(void) {
    return (gpgpu_read_status() & STATUS_RUNNING) != 0;
}

static int is_loading(void) {
    return (gpgpu_read_status() & STATUS_LOADING) != 0;
}

static int is_dumping(void) {
    return (gpgpu_read_status() & STATUS_DUMPING) != 0;
}

static int require_not_running(const char *op) {
    if (is_running()) {
        xil_printf("ERROR: %s is only allowed when not in RUNNING state.\r\n", op);
        gpgpu_print_status();
        return -1;
    }

    return 0;
}

static int require_loading(const char *op) {
    if (!is_loading()) {
        xil_printf("ERROR: %s is only allowed in LOADING state.\r\n", op);
        gpgpu_print_status();
        return -1;
    }

    return 0;
}

static int require_dumping(const char *op) {
    if (!is_dumping()) {
        xil_printf("ERROR: %s is only allowed in DUMPING state.\r\n", op);
        gpgpu_print_status();
        return -1;
    }

    return 0;
}

static int wait_until_not_busy(u32 timeout) {
    while (timeout--) {
        if ((gpgpu_read_status() & STATUS_BUSY) == 0)
            return 0;
    }

    return -1;
}

static int wait_until_done(u32 timeout) {
    while (timeout--) {
        if (gpgpu_read_status() & STATUS_DONE)
            return 0;
    }

    return -1;
}

static int wait_until_done_cleared(u32 timeout) {
    while (timeout--) {
        if ((gpgpu_read_status() & STATUS_DONE) == 0)
            return 0;
    }

    return -1;
}

static int wait_until_dumping(u32 timeout) {
    while (timeout--) {
        if (gpgpu_read_status() & STATUS_DUMPING)
            return 0;
    }

    return -1;
}

static int begin_command(u32 cmd, u32 addr, u32 wdata) {
    if (wait_until_not_busy(TIMEOUT_COUNT) != 0) {
        xil_printf("ERROR: timeout waiting for busy=0 before cmd %u\r\n", cmd);
        gpgpu_print_status();
        return -1;
    }

    gpio_write(GPIO_ADDRESS_BASE, addr);
    gpio_write(GPIO_WDATA_BASE, wdata);
    gpio_write(GPIO_CMD_BASE, cmd | VALID_BIT);

    if (wait_until_done(TIMEOUT_COUNT) != 0) {
        xil_printf("ERROR: timeout waiting for done=1 after cmd %u\r\n", cmd);
        gpgpu_print_status();
        return -1;
    }

    return 0;
}

static int end_command(u32 cmd) {
    gpio_write(GPIO_CMD_BASE, cmd);

    if (wait_until_done_cleared(TIMEOUT_COUNT) != 0) {
        xil_printf("ERROR: timeout waiting for done=0 after cmd %u\r\n", cmd);
        gpgpu_print_status();
        return -1;
    }

    return 0;
}

static int send_command(u32 cmd, u32 addr, u32 wdata) {
    if (begin_command(cmd, addr, wdata) != 0)
        return -1;

    return end_command(cmd);
}

int gpgpu_write_imem(u32 addr, u32 word) {
    if (require_loading("IMEM write") != 0)
        return -1;

    return send_command(CMD_IMEM_WRITE, addr, word);
}

int gpgpu_write_dmem(u32 addr, u32 word) {
    if (require_loading("DMEM write") != 0)
        return -1;

    return send_command(CMD_DMEM_WRITE, addr, word);
}

int gpgpu_read_imem(u32 addr, u32 *data) {
    if (require_not_running("IMEM read") != 0)
        return -1;
    
    if (begin_command(CMD_IMEM_READ, addr, 0) != 0)
        return -1;

    *data = gpio_read(GPIO_RDATA_BASE);

    return end_command(CMD_IMEM_READ);
}

int gpgpu_read_dmem(u32 addr, u32 *data) {
    if (require_not_running("DMEM read") != 0)
        return -1;
    
    if (begin_command(CMD_DMEM_READ, addr, 0) != 0)
        return -1;

    *data = gpio_read(GPIO_RDATA_BASE);

    return end_command(CMD_DMEM_READ);
}

int gpgpu_read_regfile(u32 addr, u32 *data) {
    if (require_dumping("REG read") != 0)
        return -1;

    if (begin_command(CMD_REG_READ, addr, 0) != 0)
        return -1;

    *data = gpio_read(GPIO_RDATA_BASE);

    return end_command(CMD_REG_READ);
}

int gpgpu_start_and_wait(void) {
    if (require_loading("start") != 0)
        return -1;

    xil_printf("Starting core...\r\n");

    if (send_command(CMD_WRITE_DONE, 0, 0) != 0) {
        xil_printf("ERROR: WRITE_DONE failed.\r\n");
        return -1;
    }

    xil_printf("Waiting for dumping state...\r\n");

    if (wait_until_dumping(TIMEOUT_COUNT) != 0) {
        xil_printf("ERROR: timeout waiting for dumping state.\r\n");
        gpgpu_print_status();
        return -1;
    }

    xil_printf("Core entered dumping state.\r\n");
    return 0;
}

int gpgpu_finish_readback(void) {
    if (require_dumping("READ_DONE") != 0)
        return -1;

    xil_printf("Sending READ_DONE...\r\n");

    if (send_command(CMD_READ_DONE, 0, 0) != 0) {
        xil_printf("ERROR: READ_DONE failed.\r\n");
        return -1;
    }

    xil_printf("Returned to loading state.\r\n");
    return 0;
}

int gpgpu_dump_imem_ascii(u32 offset, u32 count) {
    u32 data;

    if (offset > IMEM_WORDS || count > (IMEM_WORDS - offset)) {
        xil_printf("ERROR: IMEM dump range offset=%u count=%u exceeds IMEM_WORDS=%d\r\n",
                   offset, count, IMEM_WORDS);
        return -1;
    }

    if (require_not_running("IMEM dump") != 0)
        return -1;

    xil_printf("BEGIN_IMEM_DUMP\r\n");

    for (u32 i = 0; i < count; i++) {
        u32 addr = offset + i;

        if (gpgpu_read_imem(addr, &data) != 0)
            return -1;

        xil_printf("%04u: %08x\r\n", addr, data);
    }

    xil_printf("END_IMEM_DUMP\r\n");
    return 0;
}

int gpgpu_dump_dmem_ascii(u32 offset, u32 count) {
    u32 data;

    if (offset > DMEM_WORDS || count > (DMEM_WORDS - offset)) {
        xil_printf("ERROR: DMEM dump range offset=%u count=%u exceeds DMEM_WORDS=%d\r\n",
                   offset, count, DMEM_WORDS);
        return -1;
    }

    if (require_not_running("DMEM dump") != 0)
        return -1;

    xil_printf("BEGIN_DMEM_DUMP\r\n");

    for (u32 i = 0; i < count; i++) {
        u32 addr = offset + i;

        if (gpgpu_read_dmem(addr, &data) != 0)
            return -1;

        xil_printf("%04u: %08x\r\n", addr, data);
    }

    xil_printf("END_DMEM_DUMP\r\n");
    return 0;
}

int gpgpu_dump_regfile_ascii(void) {
    u32 data;

    if (require_dumping("REG dump") != 0)
        return -1;

    xil_printf("BEGIN_REG_DUMP\r\n");

    for (u32 i = 0; i < REG_WORDS; i++) {
        if (gpgpu_read_regfile(i, &data) != 0)
            return -1;

        xil_printf("x%02u: %08x\r\n", i, data);
    }

    xil_printf("END_REG_DUMP\r\n");
    return 0;
}