#include "gpgpu_driver.h"
#include <stddef.h>
#include <string.h>

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

/* Name and meaning of a register value or field code. */
typedef struct {
    const char *name;
    const char *meaning;
} gpgpu_text_t;

static gpgpu_text_t status_kind_text(u32 code)
{
    switch (code) {
    case GPGPU_ST_UNMAPPED:
        return (gpgpu_text_t){"unmapped", "the address is in no memory region"};
    case GPGPU_ST_PERMISSION:
        return (gpgpu_text_t){"permission", "the region does not allow this access (e.g. a store to TEX)"};
    case GPGPU_ST_MISALIGNED:
        return (gpgpu_text_t){"misaligned", "the address is not word-aligned"};
    case GPGPU_ST_SLVERR:
        return (gpgpu_text_t){"slverr", "the AXI slave returned SLVERR; a store may have happened"};
    case GPGPU_ST_DECERR:
        return (gpgpu_text_t){"decerr", "the AXI interconnect returned DECERR; a store may have happened"};
    default:
        return (gpgpu_text_t){"unknown", "status code not known to this driver"};
    }
}

static gpgpu_text_t fatal_code_text(u32 code)
{
    switch (code) {
    case GPGPU_FATAL_RLAST:
        return (gpgpu_text_t){"rlast", "an AXI read burst ended early or ran past its length"};
    case GPGPU_FATAL_UNEXPECTED:
        return (gpgpu_text_t){"unexpected", "an AXI response arrived with nothing outstanding or a wrong ID"};
    case GPGPU_FATAL_TIMEOUT:
        return (gpgpu_text_t){"timeout", "the AXI bus made no progress"};
    case GPGPU_FATAL_INTERNAL:
        return (gpgpu_text_t){"internal", "a memory subsystem invariant was violated"};
    default:
        return (gpgpu_text_t){"unknown", "fatal code not known to this driver"};
    }
}

static gpgpu_text_t fault_cause_text(u32 cause)
{
    switch (cause) {
    case GPGPU_FAULT_NONE:
        return (gpgpu_text_t){"none", "no fault since the last START"};
    case GPGPU_FAULT_MEMORY:
        return (gpgpu_text_t){"memory", "a kernel memory access failed"};
    case GPGPU_FAULT_POSTED_WRITE:
        return (gpgpu_text_t){"posted write", "a posted DDR write failed (lane unknown)"};
    case GPGPU_FAULT_FATAL:
        return (gpgpu_text_t){"fatal", "the memory subsystem locked up; `reset` required"};
    default:
        return (gpgpu_text_t){"unknown", "cause not known to this driver"};
    }
}

/* One line per error kind in FAULT_INFO: kind bit k-1 reports status code k. */
static void print_fault_kinds(u32 fault_info)
{
    u32 kinds = (fault_info & GPGPU_FAULT_KINDS_MASK) >> GPGPU_FAULT_KINDS_LSB;

    for (u32 code = 1U; kinds != 0U; ++code, kinds >>= 1) {
        if ((kinds & 1U) != 0U) {
            const gpgpu_text_t kind = status_kind_text(code);
            xil_printf("  %s: %s\r\n", kind.name, kind.meaning);
        }
    }
}

static u32 fatal_code(u32 fault_info)
{
    return (fault_info & GPGPU_FAULT_FATAL_MASK) >> GPGPU_FAULT_FATAL_LSB;
}

/* "NAME = 0xVALUE  " with the explanations aligned in one column. */
static void print_register(const char *name, u32 value)
{
    static const size_t name_column = sizeof("INFO_FEATURES") - 1U; /* longest name */

    xil_printf("%s", name);
    for (size_t i = strlen(name); i < name_column; ++i)
        xil_printf(" ");
    xil_printf(" = 0x%08x  ", (unsigned int)value);
}

static u32 count_bits(u32 mask)
{
    u32 count = 0U;
    for (; mask != 0U; mask &= mask - 1U)
        ++count;
    return count;
}

/* The set bits of mask as lane ranges, e.g. "0-3,8,10-11". */
static void print_lanes(u32 mask)
{
    const char *separator = "";
    u32 lane = 0U;

    while (mask != 0U) {
        if ((mask & 1U) == 0U) {
            mask >>= 1;
            ++lane;
            continue;
        }
        const u32 first = lane;
        while ((mask & 1U) != 0U) {
            mask >>= 1;
            ++lane;
        }
        if (lane - 1U == first)
            xil_printf("%s%u", separator, (unsigned int)first);
        else
            xil_printf("%s%u-%u", separator, (unsigned int)first, (unsigned int)(lane - 1U));
        separator = ",";
    }
}

static void print_identity(void)
{
    const u32 info = gpu_read(GPGPU_REG_INFO);
    const u32 version = (info & GPGPU_INFO_VERSION_MASK) >> GPGPU_INFO_VERSION_LSB;
    print_register("INFO", info);
    xil_printf("interface v%u (driver v%u), %u SPs per SM\r\n", (unsigned int)version,
               (unsigned int)GPGPU_INTERFACE_VERSION,
               (unsigned int)(info & GPGPU_INFO_SP_COUNT_MASK));

    const u32 info_mem = gpu_read(GPGPU_REG_INFO_MEM);
    print_register("INFO_MEM", info_mem);
    xil_printf("IMEM %u words, DMEM %u words\r\n",
               (unsigned int)((info_mem & GPGPU_INFO_MEM_IMEM_MASK) >> GPGPU_INFO_MEM_IMEM_LSB),
               (unsigned int)(info_mem & GPGPU_INFO_MEM_DMEM_MASK));

    const u32 features = gpu_read(GPGPU_REG_INFO_FEATURES);
    print_register("INFO_FEATURES", features);
    xil_printf("DDR backend %s\r\n",
               (features & GPGPU_FEATURE_DDR_MASK) != 0U ? "present" : "absent");

    const u32 khz = gpu_read(GPGPU_REG_INFO_CLOCK);
    print_register("INFO_CLOCK", khz);
    xil_printf("%u kHz = %u.%03u MHz fabric clock\r\n", (unsigned int)khz,
               (unsigned int)(khz / 1000U), (unsigned int)(khz % 1000U));

    const u32 build = gpu_read(GPGPU_REG_BUILD_ID);
    print_register("BUILD_ID", build);
    xil_printf("RTL commit %07x%s\r\n", (unsigned int)(build & GPGPU_BUILD_HASH_MASK),
               (build & GPGPU_BUILD_DIRTY_MASK) != 0U ? " plus uncommitted RTL changes (dirty)" : "");
}

static void print_control(void)
{
    const u32 status = gpgpu_read_status();
    const unsigned int idle = !!(status & GPGPU_STATUS_IDLE_MASK);
    const unsigned int running = !!(status & GPGPU_STATUS_RUNNING_MASK);
    const unsigned int stopped = !!(status & GPGPU_STATUS_STOPPED_MASK);
    const unsigned int faulted = !!(status & GPGPU_STATUS_FAULTED_MASK);

    print_register("STATUS", status);
    xil_printf("%s\r\n", running            ? "running a kernel"
                         : !idle            ? "busy: starting or draining a kernel"
                         : stopped || faulted ? "idle, but START is refused until the latch below is acknowledged"
                                            : "idle: ready for START, memories accessible");
    xil_printf("  idle = %u\r\n", idle);
    xil_printf("  running = %u\r\n", running);
    xil_printf("  stopped = %u%s\r\n", stopped,
               stopped ? "   the host STOPPED the last run; `clear` acknowledges it" : "");
    xil_printf("  faulted = %u%s\r\n", faulted,
               faulted ? "   the last run faulted; see FAULT_INFO" : "");

    const u32 irq_en = gpu_read(GPGPU_REG_IRQ_ENABLE);
    const u32 irq_st = gpu_read(GPGPU_REG_IRQ_STATUS);
    print_register("IRQ_ENABLE", irq_en);
    xil_printf("completion interrupt %s\r\n",
               (irq_en & GPGPU_IRQ_COMPLETE_MASK) != 0U ? "enabled" : "disabled");
    xil_printf("  irq_enabled = %u\r\n", (unsigned int)!!(irq_en & GPGPU_IRQ_COMPLETE_MASK));
    print_register("IRQ_STATUS", irq_st);
    xil_printf("%s\r\n", (irq_st & GPGPU_IRQ_COMPLETE_MASK) != 0U
                             ? "a kernel completed and is not acknowledged"
                             : "no completion pending");
    xil_printf("  irq_pending = %u\r\n", (unsigned int)!!(irq_st & GPGPU_IRQ_COMPLETE_MASK));
}

static void print_fault(void)
{
    const u32 info = gpu_read(GPGPU_REG_FAULT_INFO);
    const u32 cause = info & GPGPU_FAULT_CAUSE_MASK;
    const gpgpu_text_t cause_text = fault_cause_text(cause);

    print_register("FAULT_INFO", info);
    xil_printf("cause %u (%s): %s\r\n", (unsigned int)cause, cause_text.name, cause_text.meaning);
    print_fault_kinds(info);
    if (cause == GPGPU_FAULT_FATAL) {
        const gpgpu_text_t fatal = fatal_code_text(fatal_code(info));
        xil_printf("  fatal %u (%s): %s\r\n", (unsigned int)fatal_code(info), fatal.name, fatal.meaning);
    }

    /* The lane mask and PC describe a memory fault; otherwise they hold their
     * reset values. */
    const u32 lanes = gpu_read(GPGPU_REG_FAULT_LANES);
    print_register("FAULT_LANES", lanes);
    if (cause == GPGPU_FAULT_MEMORY) {
        xil_printf("%u lane(s) faulted: ", (unsigned int)count_bits(lanes));
        print_lanes(lanes);
        xil_printf("\r\n");
    } else {
        xil_printf("no memory fault\r\n");
    }

    const u32 pc = gpu_read(GPGPU_REG_FAULT_PC);
    print_register("FAULT_PC", pc);
    if (cause == GPGPU_FAULT_MEMORY)
        xil_printf("faulting instruction, IMEM word %u\r\n", (unsigned int)(pc / 4U));
    else
        xil_printf("no memory fault\r\n");
}

void gpgpu_print_status(void)
{
    print_identity();
    print_control();
    print_fault();
}

/* Print the fault report of a FAULTED GPU and return its error code. */
static int report_fault(void)
{
    const u32 info = gpu_read(GPGPU_REG_FAULT_INFO);
    const u32 cause = info & GPGPU_FAULT_CAUSE_MASK;

    if (cause == GPGPU_FAULT_FATAL) {
        const gpgpu_text_t fatal = fatal_code_text(fatal_code(info));
        xil_printf("ERROR: GPU memory subsystem fatal error (%s): %s. Run `reset`.\r\n",
                   fatal.name, fatal.meaning);
        return GPGPU_ERR_FATAL;
    }

    const u32 lanes = gpu_read(GPGPU_REG_FAULT_LANES);
    xil_printf("ERROR: kernel %s fault at IMEM word %u, %u lane(s): ",
               fault_cause_text(cause).name, (unsigned int)(gpu_read(GPGPU_REG_FAULT_PC) / 4U),
               (unsigned int)count_bits(lanes));
    print_lanes(lanes);
    xil_printf("\r\n");
    print_fault_kinds(info);
    xil_printf("Run `status` for the registers, `clear` to acknowledge before the next run.\r\n");
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
    gpu_write(GPGPU_REG_IRQ_STATUS, GPGPU_IRQ_COMPLETE_MASK);
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
    const u32 version = (info & GPGPU_INFO_VERSION_MASK) >> GPGPU_INFO_VERSION_LSB;
    if (version != GPGPU_INTERFACE_VERSION) {
        xil_printf("ERROR: GPU MMIO interface v%u (INFO=0x%08x), but this driver speaks v%u: "
                   "rebuild the host against the bitstream's RTL\r\n", (unsigned int)version,
                   (unsigned int)info, (unsigned int)GPGPU_INTERFACE_VERSION);
        return GPGPU_ERR_STATE;
    }

    /* The bitstream and this driver must come from the same RTL: the memory
     * sizes compiled in from gpgpu_platform.h must match the hardware's. */
    const u32 info_mem = gpu_read(GPGPU_REG_INFO_MEM);
    const u32 imem = (info_mem & GPGPU_INFO_MEM_IMEM_MASK) >> GPGPU_INFO_MEM_IMEM_LSB;
    const u32 dmem = info_mem & GPGPU_INFO_MEM_DMEM_MASK;
    if (imem != GPGPU_IMEM_ENTRIES || dmem != GPGPU_DMEM_ENTRIES) {
        xil_printf("ERROR: the GPU has IMEM %u / DMEM %u words (INFO_MEM=0x%08x), but this "
                   "driver was built for IMEM %u / DMEM %u: rebuild the host against the "
                   "bitstream's RTL\r\n", (unsigned int)imem, (unsigned int)dmem,
                   (unsigned int)info_mem, (unsigned int)GPGPU_IMEM_ENTRIES,
                   (unsigned int)GPGPU_DMEM_ENTRIES);
        return GPGPU_ERR_STATE;
    }

    const u32 build = gpu_read(GPGPU_REG_BUILD_ID);
    xil_printf("GPU: RTL %07x%s, %u SPs, %u kHz, IMEM %u / DMEM %u words, DDR %s\r\n",
               (unsigned int)(build & GPGPU_BUILD_HASH_MASK),
               (build & GPGPU_BUILD_DIRTY_MASK) != 0U ? "-dirty" : "",
               (unsigned int)(info & GPGPU_INFO_SP_COUNT_MASK),
               (unsigned int)gpu_read(GPGPU_REG_INFO_CLOCK), (unsigned int)imem, (unsigned int)dmem,
               (gpu_read(GPGPU_REG_INFO_FEATURES) & GPGPU_FEATURE_DDR_MASK) != 0U ? "on" : "off");

    gpu_write(GPGPU_REG_IRQ_ENABLE, 0U);
    gpu_write(GPGPU_REG_IRQ_STATUS, GPGPU_IRQ_COMPLETE_MASK); /* W1C pending completion. */

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
    gpu_write(GPGPU_REG_IRQ_STATUS, GPGPU_IRQ_COMPLETE_MASK);
#if GPGPU_USE_IRQ
    gpu_finished = 0U;
    gpu_write(GPGPU_REG_IRQ_ENABLE, GPGPU_IRQ_COMPLETE_MASK);
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
    while ((gpu_read(GPGPU_REG_IRQ_STATUS) & GPGPU_IRQ_COMPLETE_MASK) == 0U) {
    }
    gpu_write(GPGPU_REG_IRQ_STATUS, GPGPU_IRQ_COMPLETE_MASK);
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
