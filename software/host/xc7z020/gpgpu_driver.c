#include "gpgpu_driver.h"
#include <stddef.h>

#include "sleep.h"
#include "xil_exception.h"
#include "xil_io.h"
#include "xil_printf.h"
#include "xparameters.h"
#include "xpseudo_asm.h"
#include "xreg_cortexa9.h"

#if GPGPU_USE_IRQ
#include "xscugic.h"
#include "xstatus.h"
#endif

/* Zynq-7000 SLCR (UG585, System Level Control Registers). The GPU's reset
 * comes from FCLK_RESET0, bit 0 of FPGA_RST_CTRL. */
#define SLCR_LOCK              0x004U
#define SLCR_UNLOCK            0x008U
#define SLCR_FPGA_RST_CTRL     0x240U
#define SLCR_LOCK_KEY          0x767BU
#define SLCR_UNLOCK_KEY        0xDF0DU
#define SLCR_FCLK_RESET0       0x1U

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
    xil_printf("  idle = %u\r\n", (unsigned int)!!(status & GPGPU_STATUS_IDLE_MASK));
    xil_printf("  running = %u\r\n", (unsigned int)!!(status & GPGPU_STATUS_RUNNING_MASK));
    xil_printf("  stopped = %u\r\n", (unsigned int)!!(status & GPGPU_STATUS_STOPPED_MASK));
    xil_printf("  faulted = %u\r\n", (unsigned int)!!(status & GPGPU_STATUS_FAULTED_MASK));
    xil_printf("  irq_enabled = %u\r\n", (unsigned int)(irq_en & 1U));
    xil_printf("  irq_pending = %u\r\n", (unsigned int)(irq_st & 1U));
    xil_printf("INFO_MEM = 0x%08x\r\n", (unsigned int)gpu_read(GPGPU_REG_INFO_MEM));
    xil_printf("INFO_FEATURES = 0x%08x\r\n", (unsigned int)gpu_read(GPGPU_REG_INFO_FEATURES));
    xil_printf("INFO_CLOCK = %u kHz\r\n", (unsigned int)gpu_read(GPGPU_REG_INFO_CLOCK));
    xil_printf("BUILD_ID = 0x%08x\r\n", (unsigned int)gpu_read(GPGPU_REG_BUILD_ID));
    xil_printf("FAULT_INFO = 0x%08x\r\n", (unsigned int)gpu_read(GPGPU_REG_FAULT_INFO));
    xil_printf("FAULT_LANES = 0x%08x\r\n", (unsigned int)gpu_read(GPGPU_REG_FAULT_LANES));
    xil_printf("FAULT_PC = 0x%08x\r\n", (unsigned int)gpu_read(GPGPU_REG_FAULT_PC));
}

static const char *status_kind_name(u32 code)
{
    switch (code) {
    case GPGPU_ST_UNMAPPED:   return "unmapped";
    case GPGPU_ST_PERMISSION: return "permission";
    case GPGPU_ST_MISALIGNED: return "misaligned";
    case GPGPU_ST_SLVERR:     return "slverr";
    case GPGPU_ST_DECERR:     return "decerr";
    default:                  return "unknown";
    }
}

/* Print the fault report of a FAULTED GPU and return its error code. */
static int report_fault(void)
{
    const u32 info = gpu_read(GPGPU_REG_FAULT_INFO);
    const u32 cause = info & GPGPU_FAULT_CAUSE_MASK;

    if (cause == GPGPU_FAULT_FATAL) {
        xil_printf("ERROR: GPU memory subsystem fatal error, code %u: reset required\r\n",
                   (unsigned int)((info & GPGPU_FAULT_FATAL_MASK) >> GPGPU_FAULT_FATAL_LSB));
        return GPGPU_ERR_FATAL;
    }

    const u32 kinds = (info & GPGPU_FAULT_KINDS_MASK) >> GPGPU_FAULT_KINDS_LSB;
    xil_printf("ERROR: kernel fault (cause %u) at pc 0x%08x: lanes 0x%08x,",
               (unsigned int)cause, (unsigned int)gpu_read(GPGPU_REG_FAULT_PC),
               (unsigned int)gpu_read(GPGPU_REG_FAULT_LANES));
    /* Kind bit k-1 reports status code k. */
    for (u32 code = 1U; (kinds >> (code - 1U)) != 0U; ++code) {
        if ((kinds & (1U << (code - 1U))) != 0U)
            xil_printf(" %s", status_kind_name(code));
    }
    xil_printf("\r\nRun `clear` to acknowledge the fault before the next run.\r\n");
    return GPGPU_ERR_FAULT;
}

void gpgpu_clear(void)
{
    gpu_write(GPGPU_REG_STATUS, GPGPU_STATUS_STOPPED_MASK | GPGPU_STATUS_FAULTED_MASK);
}

/* The GPU answers a rejected MMIO access with SLVERR/DECERR, which the ARM
 * takes as a data abort. Returning would re-execute the access, so report it
 * and halt instead of the BSP's silent loop. */
static void gpgpu_data_abort_handler(void *ref)
{
    const u32 address = mfcp(XREG_CP15_DATA_FAULT_ADDRESS);
    (void)ref;
    xil_printf("\r\nFATAL: data abort at 0x%08x (DFSR 0x%08x)", (unsigned int)address,
               (unsigned int)mfcp(XREG_CP15_DATA_FAULT_STATUS));
    if (address >= (u32)GPGPU_BASEADDR)
        xil_printf(": GPU MMIO error at offset 0x%x", (unsigned int)(address - (u32)GPGPU_BASEADDR));
    xil_printf(". Halted.\r\n");
    for (;;) {
    }
}

static int require_idle(const char *operation)
{
    const u32 status = gpgpu_read_status();
    if ((status & GPGPU_STATUS_IDLE_MASK) == 0U) {
        xil_printf("ERROR: %s requires an idle GPU (STATUS=0x%08x)\r\n",
                   operation, (unsigned int)status);
        return GPGPU_ERR_STATE;
    }
    return 0;
}

static int check_index(const char *memory, u32 index, u32 depth)
{
    if (index >= depth) {
        xil_printf("ERROR: %s word index %u out of range (0..%u)\r\n",
                   memory, (unsigned int)index, (unsigned int)(depth - 1U));
        return GPGPU_ERR_STATE;
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
        return GPGPU_ERR_STATE;
    }
    return 0;
}

int gpgpu_write_imem(u32 index, u32 word)
{
    if (check_index("IMEM", index, GPGPU_IMEM_ENTRIES) != 0 ||
        require_idle("IMEM write") != 0)
        return GPGPU_ERR_STATE;
    gpu_write(GPGPU_IMEM_BASE + 4U * index, word);
    return 0;
}

int gpgpu_write_dmem(u32 index, u32 word)
{
    if (check_index("DMEM", index, GPGPU_DMEM_ENTRIES) != 0 ||
        require_idle("DMEM write") != 0)
        return GPGPU_ERR_STATE;
    gpu_write(GPGPU_DMEM_BASE + 4U * index, word);
    return 0;
}

int gpgpu_read_imem(u32 index, u32 *data)
{
    if (data == NULL || check_index("IMEM", index, GPGPU_IMEM_ENTRIES) != 0 ||
        require_idle("IMEM read") != 0)
        return GPGPU_ERR_STATE;
    *data = gpu_read(GPGPU_IMEM_BASE + 4U * index);
    return 0;
}

int gpgpu_read_dmem(u32 index, u32 *data)
{
    if (data == NULL || check_index("DMEM", index, GPGPU_DMEM_ENTRIES) != 0 ||
        require_idle("DMEM read") != 0)
        return GPGPU_ERR_STATE;
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
        return GPGPU_ERR_STATE;

    result = XScuGic_CfgInitialize(&gic, config, config->CpuBaseAddress);
    if (result != XST_SUCCESS)
        return GPGPU_ERR_STATE;

    XScuGic_SetPriorityTriggerType(&gic, GPGPU_IRQ_ID, 0xA0U, 0x01U);
    result = XScuGic_Connect(&gic, GPGPU_IRQ_ID,
                             (Xil_InterruptHandler)gpgpu_interrupt_handler,
                             NULL);
    if (result != XST_SUCCESS)
        return GPGPU_ERR_STATE;

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
    Xil_ExceptionRegisterHandler(XIL_EXCEPTION_ID_DATA_ABORT_INT,
                                 (Xil_ExceptionHandler)gpgpu_data_abort_handler, NULL);

    const u32 info = gpu_read(GPGPU_REG_INFO);
    if ((info >> 16) != GPGPU_INTERFACE_VERSION) {
        xil_printf("ERROR: unsupported GPU MMIO version: INFO=0x%08x\r\n",
                   (unsigned int)info);
        return GPGPU_ERR_STATE;
    }

    /* The bitstream and this driver must come from the same RTL: the memory
     * sizes compiled in from gpgpu_platform.h must match the hardware's. */
    const u32 info_mem = gpu_read(GPGPU_REG_INFO_MEM);
    if ((info_mem >> 16) != GPGPU_IMEM_ENTRIES || (info_mem & 0xFFFFU) != GPGPU_DMEM_ENTRIES) {
        xil_printf("ERROR: GPU memory sizes INFO_MEM=0x%08x do not match this driver "
                   "(IMEM %u, DMEM %u words)\r\n", (unsigned int)info_mem,
                   (unsigned int)GPGPU_IMEM_ENTRIES, (unsigned int)GPGPU_DMEM_ENTRIES);
        return GPGPU_ERR_STATE;
    }

    const u32 build = gpu_read(GPGPU_REG_BUILD_ID);
    xil_printf("GPU: RTL %07x%s, %u cores, %u kHz, IMEM %u / DMEM %u words, DDR %s\r\n",
               (unsigned int)(build & GPGPU_BUILD_HASH_MASK),
               (build & GPGPU_BUILD_DIRTY_MASK) != 0U ? "-dirty" : "",
               (unsigned int)(info & 0xFFFFU), (unsigned int)gpu_read(GPGPU_REG_INFO_CLOCK),
               (unsigned int)GPGPU_IMEM_ENTRIES, (unsigned int)GPGPU_DMEM_ENTRIES,
               (gpu_read(GPGPU_REG_INFO_FEATURES) & GPGPU_FEATURE_DDR_MASK) != 0U ? "on" : "off");

    gpu_write(GPGPU_REG_IRQ_ENABLE, 0U);
    gpu_write(GPGPU_REG_IRQ_STATUS, 1U); /* W1C pending completion. */

#if GPGPU_USE_IRQ
    if (initialize_interrupts() != 0) {
        xil_printf("ERROR: GIC initialization failed\r\n");
        return GPGPU_ERR_STATE;
    }
#endif
    return GPGPU_OK;
}

int gpgpu_reset(void)
{
    const UINTPTR slcr = (UINTPTR)XPS_SYS_CTRL_BASEADDR;

    xil_printf("Resetting the PL (FCLK_RESET0)...\r\n");
    Xil_Out32(slcr + SLCR_UNLOCK, SLCR_UNLOCK_KEY);
    Xil_Out32(slcr + SLCR_FPGA_RST_CTRL, Xil_In32(slcr + SLCR_FPGA_RST_CTRL) | SLCR_FCLK_RESET0);
    usleep(10);
    Xil_Out32(slcr + SLCR_FPGA_RST_CTRL, Xil_In32(slcr + SLCR_FPGA_RST_CTRL) & ~SLCR_FCLK_RESET0);
    Xil_Out32(slcr + SLCR_LOCK, SLCR_LOCK_KEY);
    usleep(10); /* proc_sys_reset releases the GPU a few cycles later */
    return gpgpu_init();
}

int gpgpu_start_and_wait(void)
{
    u32 status;

    if (require_idle("START") != 0)
        return GPGPU_ERR_STATE;
    status = gpgpu_read_status();
    if ((status & GPGPU_STATUS_FAULTED_MASK) != 0U) {
        report_fault();
        xil_printf("ERROR: GPU FAULTED latch set; refusing START\r\n");
        return GPGPU_ERR_STATE;
    }
    if ((status & GPGPU_STATUS_STOPPED_MASK) != 0U) {
        xil_printf("ERROR: GPU STOPPED latch set; refusing START (run `clear`)\r\n");
        return GPGPU_ERR_STATE;
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
    gpu_write(GPGPU_REG_CONTROL, GPGPU_CONTROL_START_MASK);

    /* No timeout: a kernel that never completes blocks here forever. */
#if GPGPU_USE_IRQ
    while (gpu_finished == 0U) {
        /* The ISR clears the GPU IRQ and sets gpu_finished. */
    }
    gpu_write(GPGPU_REG_IRQ_ENABLE, 0U);
#else
    while ((gpu_read(GPGPU_REG_IRQ_STATUS) & 1U) == 0U) {
    }
    gpu_write(GPGPU_REG_IRQ_STATUS, 1U);
#endif

    status = gpgpu_read_status();
    if ((status & GPGPU_STATUS_IDLE_MASK) == 0U) {
        xil_printf("ERROR: completion observed, but GPU is not IDLE\r\n");
        gpgpu_print_status();
        return GPGPU_ERR_STATE;
    }
    /* FAULTED stays set until `clear`, so callers that only check STATUS
     * (e.g. the UART tools) see the fault too. */
    if ((status & GPGPU_STATUS_FAULTED_MASK) != 0U)
        return report_fault();

    xil_printf("Core entered idle state.\r\n");
    return GPGPU_OK;
}

int gpgpu_dump_imem_ascii(u32 offset, u32 count)
{
    u32 word;
    if (check_span("IMEM", offset, count, GPGPU_IMEM_ENTRIES) != 0 ||
        require_idle("IMEM dump") != 0)
        return GPGPU_ERR_STATE;
    xil_printf("BEGIN_IMEM_DUMP\r\n");
    for (u32 i = 0U; i < count; ++i) {
        if (gpgpu_read_imem(offset + i, &word) != 0)
            return GPGPU_ERR_STATE;
        xil_printf("%04u: %08x\r\n", (unsigned int)(offset + i),
                   (unsigned int)word);
    }
    xil_printf("END_IMEM_DUMP\r\n");
    return 0;
}

int gpgpu_dump_dmem_ascii(u32 offset, u32 count)
{
    u32 word;
    if (check_span("DMEM", offset, count, GPGPU_DMEM_ENTRIES) != 0 ||
        require_idle("DMEM dump") != 0)
        return GPGPU_ERR_STATE;
    xil_printf("BEGIN_DMEM_DUMP\r\n");
    for (u32 i = 0U; i < count; ++i) {
        if (gpgpu_read_dmem(offset + i, &word) != 0)
            return GPGPU_ERR_STATE;
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
    return GPGPU_ERR_STATE;
}

int gpgpu_dump_regfile_ascii(void)
{
    xil_printf("ERROR: SP regfile has no MMIO read window\r\n");
    return GPGPU_ERR_STATE;
}
