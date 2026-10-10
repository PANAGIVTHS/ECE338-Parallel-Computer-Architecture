#include "gpgpu_driver.h"
#include <stddef.h>

#include "xil_io.h"
#include "xil_printf.h"

#if GPGPU_USE_IRQ
#include "xparameters.h"
#include "xil_exception.h"
#include "xscugic.h"
#include "xstatus.h"
#endif

/* AXI4-Lite performs complete 32-bit accesses. The RTL returns BRESP/RRESP;
 * Xil_In32/Xil_Out32 do not expose those response codes. We therefore check
 * bounds and execution state BEFORE issuing accesses that RTL would reject.
 */
static inline u32 gpu_read(u32 byte_offset)
{
    return Xil_In32((UINTPTR)GPGPU_BASEADDR + byte_offset);
}

static inline void gpu_write(u32 byte_offset, u32 value)
{
    Xil_Out32((UINTPTR)GPGPU_BASEADDR + byte_offset, value);
}

u32 gpgpu_read_status(void)
{
    return gpu_read(GPGPU_REG_STATUS);
}

void gpgpu_print_status(void)
{
    const u32 info = gpu_read(GPGPU_REG_INFO);
    const u32 status = gpgpu_read_status();
    const u32 irq_en = gpu_read(GPGPU_REG_IRQ_ENABLE);
    const u32 irq_st = gpu_read(GPGPU_REG_IRQ_STATUS);

    xil_printf("INFO = 0x%08x\r\n", (unsigned int)info);
    xil_printf("STATUS = 0x%08x\r\n", (unsigned int)status);
    xil_printf("  idle = %u\r\n", (unsigned int)!!(status & GPGPU_STATUS_IDLE));
    xil_printf("  running = %u\r\n", (unsigned int)!!(status & GPGPU_STATUS_RUNNING));
    xil_printf("  stopped = %u\r\n", (unsigned int)!!(status & GPGPU_STATUS_STOPPED));
    xil_printf("  irq_enabled = %u\r\n", (unsigned int)(irq_en & 1U));
    xil_printf("  irq_pending = %u\r\n", (unsigned int)(irq_st & 1U));
}

static int require_idle(const char *operation)
{
    const u32 status = gpgpu_read_status();
    if ((status & GPGPU_STATUS_IDLE) == 0U) {
        xil_printf("ERROR: %s requires an idle GPU (STATUS=0x%08x)\r\n",
                   operation, (unsigned int)status);
        return -1;
    }
    return 0;
}

static int check_index(const char *memory, u32 index, u32 depth)
{
    if (index >= depth) {
        xil_printf("ERROR: %s word index %u out of range (0..%u)\r\n",
                   memory, (unsigned int)index, (unsigned int)(depth - 1U));
        return -1;
    }
    return 0;
}

static int check_span(const char *memory, u32 offset, u32 count, u32 depth)
{
    /* Subtraction avoids overflow in offset + count. */
    if (offset > depth || count > depth - offset) {
        xil_printf("ERROR: %s range offset=%u count=%u exceeds %u words\r\n",
                   memory, (unsigned int)offset,
                   (unsigned int)count, (unsigned int)depth);
        return -1;
    }
    return 0;
}

int gpgpu_write_imem(u32 index, u32 word)
{
    if (check_index("IMEM", index, IMEM_WORDS) != 0 ||
        require_idle("IMEM write") != 0)
        return -1;
    gpu_write(GPGPU_IMEM_BASE + 4U * index, word);
    return 0;
}

int gpgpu_write_dmem(u32 index, u32 word)
{
    if (check_index("DMEM", index, DMEM_WORDS) != 0 ||
        require_idle("DMEM write") != 0)
        return -1;
    gpu_write(GPGPU_DMEM_BASE + 4U * index, word);
    return 0;
}

int gpgpu_read_imem(u32 index, u32 *data)
{
    if (data == NULL || check_index("IMEM", index, IMEM_WORDS) != 0 ||
        require_idle("IMEM read") != 0)
        return -1;
    *data = gpu_read(GPGPU_IMEM_BASE + 4U * index);
    return 0;
}

int gpgpu_read_dmem(u32 index, u32 *data)
{
    if (data == NULL || check_index("DMEM", index, DMEM_WORDS) != 0 ||
        require_idle("DMEM read") != 0)
        return -1;
    *data = gpu_read(GPGPU_DMEM_BASE + 4U * index);
    return 0;
}

#if GPGPU_USE_IRQ
static XScuGic gic;
static volatile u32 gpu_finished = 0U;

static void gpgpu_interrupt_handler(void *ref)
{
    (void)ref;
    /* Level-sensitive IRQ: clear its source before returning to the GIC. */
    gpu_write(GPGPU_REG_IRQ_STATUS, 1U);
    (void)gpu_read(GPGPU_REG_IRQ_STATUS); /* Read back to drain the AXI write. */
    gpu_finished = 1U;
}

static int initialize_interrupts(void)
{
    XScuGic_Config *config;
    int result;

    /* Vitis 2026.x SDT standalone GIC driver looks up by base address. */
    config = XScuGic_LookupConfig(XPAR_XSCUGIC_0_BASEADDR);
    if (config == NULL)
        return -1;

    result = XScuGic_CfgInitialize(&gic, config, config->CpuBaseAddress);
    if (result != XST_SUCCESS)
        return -1;

    XScuGic_SetPriorityTriggerType(&gic, GPGPU_IRQ_ID, 0xA0U, 0x01U);
    result = XScuGic_Connect(&gic, GPGPU_IRQ_ID,
                             (Xil_InterruptHandler)gpgpu_interrupt_handler,
                             NULL);
    if (result != XST_SUCCESS)
        return -1;

    Xil_ExceptionInit();
    Xil_ExceptionRegisterHandler(XIL_EXCEPTION_ID_INT,
                                 (Xil_ExceptionHandler)XScuGic_InterruptHandler,
                                 &gic);
    XScuGic_Enable(&gic, GPGPU_IRQ_ID);
    Xil_ExceptionEnable();
    return 0;
}
#endif

int gpgpu_init(void)
{
    const u32 info = gpu_read(GPGPU_REG_INFO);
    if ((info >> 16) != 1U) {
        xil_printf("ERROR: unsupported GPU MMIO version: INFO=0x%08x\r\n",
                   (unsigned int)info);
        return -1;
    }

    gpu_write(GPGPU_REG_IRQ_ENABLE, 0U);
    gpu_write(GPGPU_REG_IRQ_STATUS, 1U); /* W1C pending completion. */

#if GPGPU_USE_IRQ
    if (initialize_interrupts() != 0) {
        xil_printf("ERROR: GIC initialization failed\r\n");
        return -1;
    }
#endif
    return 0;
}

int gpgpu_start_and_wait(void)
{
    u32 remaining = GPGPU_WAIT_LIMIT;
    u32 status;

    if (require_idle("START") != 0)
        return -1;
    status = gpgpu_read_status();
    if ((status & GPGPU_STATUS_STOPPED) != 0U) {
        xil_printf("ERROR: GPU STOPPED latch set; refusing START\r\n");
        return -1;
    }

    /* Arm BEFORE START. IRQ_STATUS becomes set on normal completion even
     * with IRQ_ENABLE=0, so polling uses this sticky event rather than IDLE,
     * which may already be high when the START AXI write completes. */
    gpu_write(GPGPU_REG_IRQ_ENABLE, 0U);
    gpu_write(GPGPU_REG_IRQ_STATUS, 1U);
#if GPGPU_USE_IRQ
    gpu_finished = 0U;
    gpu_write(GPGPU_REG_IRQ_ENABLE, 1U);
#endif

    xil_printf("Starting core...\r\n");
    gpu_write(GPGPU_REG_CONTROL, GPGPU_CONTROL_START);

#if GPGPU_USE_IRQ
    while (remaining-- != 0U && gpu_finished == 0U) {
        /* The ISR clears the GPU IRQ and sets gpu_finished. */
    }
    if (gpu_finished == 0U) {
        xil_printf("ERROR: timeout waiting for GPU interrupt\r\n");
        gpgpu_print_status();
        gpu_write(GPGPU_REG_IRQ_ENABLE, 0U);
        return -1;
    }
    gpu_write(GPGPU_REG_IRQ_ENABLE, 0U);
#else
    while (remaining-- != 0U) {
        if ((gpu_read(GPGPU_REG_IRQ_STATUS) & 1U) != 0U)
            break;
    }
    if ((gpu_read(GPGPU_REG_IRQ_STATUS) & 1U) == 0U) {
        xil_printf("ERROR: timeout waiting for GPU completion\r\n");
        gpgpu_print_status();
        return -1;
    }
    gpu_write(GPGPU_REG_IRQ_STATUS, 1U);
#endif

    if ((gpgpu_read_status() & GPGPU_STATUS_IDLE) == 0U) {
        xil_printf("ERROR: completion observed, but GPU is not IDLE\r\n");
        gpgpu_print_status();
        return -1;
    }

    xil_printf("Core entered idle state.\r\n");
    return 0;
}

int gpgpu_dump_imem_ascii(u32 offset, u32 count)
{
    u32 word;
    if (check_span("IMEM", offset, count, IMEM_WORDS) != 0 ||
        require_idle("IMEM dump") != 0)
        return -1;
    xil_printf("BEGIN_IMEM_DUMP\r\n");
    for (u32 i = 0U; i < count; ++i) {
        if (gpgpu_read_imem(offset + i, &word) != 0)
            return -1;
        xil_printf("%04u: %08x\r\n", (unsigned int)(offset + i),
                   (unsigned int)word);
    }
    xil_printf("END_IMEM_DUMP\r\n");
    return 0;
}

int gpgpu_dump_dmem_ascii(u32 offset, u32 count)
{
    u32 word;
    if (check_span("DMEM", offset, count, DMEM_WORDS) != 0 ||
        require_idle("DMEM dump") != 0)
        return -1;
    xil_printf("BEGIN_DMEM_DUMP\r\n");
    for (u32 i = 0U; i < count; ++i) {
        if (gpgpu_read_dmem(offset + i, &word) != 0)
            return -1;
        xil_printf("%04u: %08x\r\n", (unsigned int)(offset + i),
                   (unsigned int)word);
    }
    xil_printf("END_DMEM_DUMP\r\n");
    return 0;
}

int gpgpu_read_regfile(u32 index, u32 *data)
{
    (void)index;
    (void)data;
    xil_printf("ERROR: SP regfile has no MMIO read window\r\n");
    return -1;
}

int gpgpu_dump_regfile_ascii(void)
{
    xil_printf("ERROR: SP regfile has no MMIO read window\r\n");
    return -1;
}
