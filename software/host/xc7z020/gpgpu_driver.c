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
        xil_printf("byte address of the faulting instruction (see dumpimem)\r\n");
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
    xil_printf("ERROR: kernel %s fault at pc 0x%08x, %u lane(s): ",
               fault_cause_text(cause).name, (unsigned int)gpu_read(GPGPU_REG_FAULT_PC),
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

/* `verbose` prints the start and idle messages, which the UART tools expect;
 * errors are always printed. */
static int start_and_wait(int verbose)
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

    if (verbose)
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

    if (verbose)
        xil_printf("Core entered idle state.\r\n");
    return GPGPU_OK;
}

int gpgpu_start_and_wait(void)
{
    return start_and_wait(1);
}

int gpgpu_run_quiet(void)
{
    return start_and_wait(0);
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
        xil_printf("0x%08x: 0x%08x\r\n", (unsigned int)(4U * (offset + i)),
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
        xil_printf("0x%08x: 0x%08x\r\n", (unsigned int)(4U * (offset + i)),
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

/* ------------------------------------------------------------------------
 * Performance counters
 * ------------------------------------------------------------------------ */

/* Names, groups and kinds come from PerfPkg; the name tables of the counters
 * end with the count. */
static const char *const perf_global_names[] = GPGPU_PERF_GLOBAL_NAMES;
static const char *const perf_leaf_names[] = GPGPU_PERF_WARP_LEAF_NAMES;
static const char *const perf_group_names[] = GPGPU_PERF_GROUP_NAMES;
static const char *const perf_global_group_names[] = GPGPU_PERF_GLOBAL_GROUP_NAMES;
static const u32 perf_leaf_group[] = GPGPU_PERF_WARP_LEAF_GROUP;
static const u32 perf_global_group_of[] = GPGPU_PERF_GLOBAL_GROUP_OF;
static const u32 perf_global_kind[] = GPGPU_PERF_GLOBAL_KIND;
#define PERF_COUNT_OF(table) (sizeof(table) / sizeof((table)[0]))
#define PERF_GROUP_COUNT PERF_COUNT_OF(perf_group_names)
#define PERF_GLOBAL_GROUP_COUNT PERF_COUNT_OF(perf_global_group_names)

_Static_assert(PERF_COUNT_OF(perf_global_names) == GPGPU_PERF_GLOBAL_COUNT + 1U,
               "PERF_GLOBAL_NAMES must list every global counter, then the count");
_Static_assert(PERF_COUNT_OF(perf_leaf_names) == GPGPU_PERF_WARP_LEAF_COUNT + 1U,
               "PERF_WARP_LEAF_NAMES must list every warp leaf, then the count");
_Static_assert(PERF_COUNT_OF(perf_leaf_group) == GPGPU_PERF_WARP_LEAF_COUNT,
               "PERF_WARP_LEAF_GROUP must give every warp leaf a group");
_Static_assert(PERF_COUNT_OF(perf_global_group_of) == GPGPU_PERF_GLOBAL_COUNT,
               "PERF_GLOBAL_GROUP_OF must give every global counter a group");
_Static_assert(PERF_COUNT_OF(perf_global_kind) == GPGPU_PERF_GLOBAL_COUNT,
               "PERF_GLOBAL_KIND must give every global counter a kind");

static u64 perf_read_counter(u32 byte_offset)
{
    /* Stable while idle: the low and high words cannot tear. */
    const u32 lo = gpu_read(byte_offset);
    const u32 hi = gpu_read(byte_offset + GPGPU_PERF_HI_OFFSET);
    return ((u64)hi << 32) | lo;
}

int gpgpu_perf_read(gpgpu_perf_t *perf)
{
    if (require_idle("perf read") != 0)
        return GPGPU_ERR_STATE;
    for (u32 c = 0U; c < GPGPU_PERF_GLOBAL_COUNT; c++)
        perf->global[c] = perf_read_counter(GPGPU_PERF_GLOBAL_BASE + GPGPU_PERF_COUNTER_BYTES * c);
    for (u32 w = 0U; w < GPGPU_WARPS_PER_SM; w++)
        for (u32 l = 0U; l < GPGPU_PERF_WARP_LEAF_COUNT; l++)
            perf->warp[w][l] = perf_read_counter(GPGPU_PERF_WARP_BASE + GPGPU_PERF_WARP_STRIDE * w +
                                                 GPGPU_PERF_COUNTER_BYTES * l);
    return GPGPU_OK;
}

void gpgpu_perf_add(gpgpu_perf_t *total, const gpgpu_perf_t *run)
{
    for (u32 c = 0U; c < GPGPU_PERF_GLOBAL_COUNT; c++)
        total->global[c] += run->global[c];
    for (u32 w = 0U; w < GPGPU_WARPS_PER_SM; w++)
        for (u32 l = 0U; l < GPGPU_PERF_WARP_LEAF_COUNT; l++)
            total->warp[w][l] += run->warp[w][l];
}

static u64 perf_leaf_sum(const gpgpu_perf_t *perf, u32 warp)
{
    u64 sum = 0U;
    for (u32 l = 0U; l < GPGPU_PERF_WARP_LEAF_COUNT; l++)
        sum += perf->warp[warp][l];
    return sum;
}

/* xil_printf has no 64-bit integers: format a u64 in decimal. */
static const char *perf_u64(u64 value, char buffer[21])
{
    char *p = &buffer[20];
    *p = '\0';
    do {
        *--p = (char)('0' + (value % 10U));
        value /= 10U;
    } while (value != 0U);
    return p;
}

#define PERF_NUMBER_WIDTH 14U

static void perf_pad(size_t printed, size_t width)
{
    for (size_t i = printed; i < width; i++)
        xil_printf(" ");
}

/* A number right-aligned in PERF_NUMBER_WIDTH columns. */
static void perf_number(u64 value)
{
    char digits[21];
    const char *text = perf_u64(value, digits);
    perf_pad(strlen(text), PERF_NUMBER_WIDTH);
    xil_printf("%s", text);
}

/* The widest counter, leaf or group name, for the name column. */
static size_t perf_name_width(void)
{
    size_t width = 0U;
    for (u32 c = 0U; c < GPGPU_PERF_GLOBAL_COUNT; c++)
        width = strlen(perf_global_names[c]) > width ? strlen(perf_global_names[c]) : width;
    for (u32 l = 0U; l < GPGPU_PERF_WARP_LEAF_COUNT; l++)
        width = strlen(perf_leaf_names[l]) > width ? strlen(perf_leaf_names[l]) : width;
    for (u32 group = 0U; group < PERF_GROUP_COUNT; group++)
        width = strlen(perf_group_names[group]) > width ? strlen(perf_group_names[group]) : width;
    return width;
}

/* "NAME   12.34%   total   per run" after `indent` spaces, the columns aligned
 * whatever the indent: the percentage of `whole` only for a count of cycles,
 * the per-run column only for several runs. */
#define PERF_LINE_INDENT 4U
#define PERF_LEAF_INDENT 6U
static void perf_line(size_t indent, const char *name, size_t width, u64 part, u64 whole, int cycles, u32 runs)
{
    perf_pad(0U, indent);
    xil_printf("%s", name);
    perf_pad(indent + strlen(name), PERF_LEAF_INDENT + width);
    if (cycles) {
        const u64 x100 = whole == 0U ? 0U : (part * 10000U) / whole;
        xil_printf("  %3u.%02u%%", (unsigned int)(x100 / 100U), (unsigned int)(x100 % 100U));
    } else {
        xil_printf("         ");
    }
    perf_number(part);
    if (runs > 1U)
        perf_number(part / runs);
    xil_printf("\r\n");
}

/* `numerator / denominator` with three decimals, or "-" for no denominator. */
static void perf_ratio(const char *name, u64 numerator, u64 denominator)
{
    if (denominator == 0U) {
        xil_printf("        %s: -\r\n", name);
        return;
    }
    const u64 x1000 = (numerator * 1000U) / denominator;
    xil_printf("        %s: %u.%03u\r\n", name, (unsigned int)(x1000 / 1000U), (unsigned int)(x1000 % 1000U));
}

/* `numerator / denominator` as a percentage, or "-" for no denominator. */
static void perf_percent(const char *name, u64 numerator, u64 denominator)
{
    if (denominator == 0U) {
        xil_printf("        %s: -\r\n", name);
        return;
    }
    const u64 x100 = (numerator * 10000U) / denominator;
    xil_printf("        %s: %u.%02u%%\r\n", name, (unsigned int)(x100 / 100U), (unsigned int)(x100 % 100U));
}

static u32 perf_rule(int holds, const char *rule)
{
    if (holds)
        return 0U;
    xil_printf("  PERF CHECK FAILED: %s\r\n", rule);
    return 1U;
}

/* The consistency rules of docs/perf-counters-spec.md §6; returns the number
 * that fail, printing each. */
static u32 perf_check(const gpgpu_perf_t *perf)
{
    const u64 *g = perf->global;
    const u64 kernel = g[GPGPU_PERF_KERNEL_CYCLES];
    u64 ring_full_leaves = 0U;
    u32 failed = 0U;

    for (u32 w = 0U; w < GPGPU_WARPS_PER_SM; w++) {
        failed += perf_rule(g[GPGPU_PERF_RUN_RESET] + g[GPGPU_PERF_RUN_DRAIN] + perf_leaf_sum(perf, w) == kernel,
                            "reset + drain + a warp's leaves = KERNEL_CYCLES");
        ring_full_leaves += perf->warp[w][GPGPU_PERF_WARP_ST_RING_FULL];
    }
    failed += perf_rule(g[GPGPU_PERF_AW_TRANSFER] + g[GPGPU_PERF_AW_BLOCKED] + g[GPGPU_PERF_AW_IDLE] == kernel,
                        "the AW partition sums to KERNEL_CYCLES");
    failed += perf_rule(g[GPGPU_PERF_W_TRANSFER] + g[GPGPU_PERF_W_BLOCKED] + g[GPGPU_PERF_W_WAIT_AW] +
                        g[GPGPU_PERF_W_IDLE] == kernel,
                        "the W partition sums to KERNEL_CYCLES");
    failed += perf_rule(ring_full_leaves <= g[GPGPU_PERF_WR_RING_FULL], "WARP_ST_RING_FULL <= WR_RING_FULL");
    failed += perf_rule(g[GPGPU_PERF_BRAM_BUSY] <= g[GPGPU_PERF_BRAM_ACCESSES] &&
                        g[GPGPU_PERF_BRAM_ACCESSES] <= GPGPU_BRAM_PORTS * g[GPGPU_PERF_BRAM_BUSY],
                        "BRAM_BUSY <= BRAM_ACCESSES <= BRAM_PORTS x BRAM_BUSY");
    return failed;
}

/* The values derived from one group of global counters (spec §5). */
static void perf_derived(u32 group, const u64 *g, u32 khz)
{
    const u64 kernel = g[GPGPU_PERF_KERNEL_CYCLES];
    const u64 beat_bytes = GPGPU_AXI_DATA_W / 8U;
    const u64 beat_words = beat_bytes / GPGPU_BYTES_PER_WORD;
    char digits[21];

    switch (group) {
    case GPGPU_PERF_GLOBAL_GROUP_W:
        if (kernel != 0U && khz != 0U)
            /* bytes per cycle x cycles per second */
            xil_printf("        DDR write bandwidth: %s MB/s\r\n",
                       perf_u64((g[GPGPU_PERF_W_TRANSFER] * beat_bytes * khz) / (kernel * 1000U), digits));
        perf_ratio("Beats per burst (W_TRANSFER / AW_TRANSFER)", g[GPGPU_PERF_W_TRANSFER], g[GPGPU_PERF_AW_TRANSFER]);
        break;
    case GPGPU_PERF_GLOBAL_GROUP_WRITE_RING:
        perf_ratio("Average write slots in use (WR_INFLIGHT_SUM / KERNEL_CYCLES)", g[GPGPU_PERF_WR_INFLIGHT_SUM],
                   kernel);
        perf_ratio("Average slot lifetime, cycles (WR_INFLIGHT_SUM / AW_TRANSFER)", g[GPGPU_PERF_WR_INFLIGHT_SUM],
                   g[GPGPU_PERF_AW_TRANSFER]);
        perf_ratio("Average B latency, cycles (WR_OWED_SUM / AW_TRANSFER)", g[GPGPU_PERF_WR_OWED_SUM],
                   g[GPGPU_PERF_AW_TRANSFER]);
        break;
    case GPGPU_PERF_GLOBAL_GROUP_COALESCING:
        perf_ratio("Lane stores per burst (WR_LANE_STORES / AW_TRANSFER)", g[GPGPU_PERF_WR_LANE_STORES],
                   g[GPGPU_PERF_AW_TRANSFER]);
        perf_percent("Useful bytes written (word x WR_LANE_STORES / beat x W_TRANSFER)",
                     GPGPU_BYTES_PER_WORD * g[GPGPU_PERF_WR_LANE_STORES], beat_bytes * g[GPGPU_PERF_W_TRANSFER]);
        if (beat_words * g[GPGPU_PERF_W_TRANSFER] >= g[GPGPU_PERF_WR_LANE_STORES]) {
            xil_printf("        Unwritten words in W beats (words per beat x W_TRANSFER - WR_LANE_STORES): %s\r\n",
                       perf_u64(beat_words * g[GPGPU_PERF_W_TRANSFER] - g[GPGPU_PERF_WR_LANE_STORES], digits));
        }
        break;
    case GPGPU_PERF_GLOBAL_GROUP_BRAM:
        perf_ratio("Ports used per busy cycle (BRAM_ACCESSES / BRAM_BUSY)", g[GPGPU_PERF_BRAM_ACCESSES],
                   g[GPGPU_PERF_BRAM_BUSY]);
        perf_ratio("Deferrals per access (BRAM_DEFERRED / BRAM_ACCESSES)", g[GPGPU_PERF_BRAM_DEFERRED],
                   g[GPGPU_PERF_BRAM_ACCESSES]);
        break;
    default:
        break;
    }
}

u32 gpgpu_perf_report(const gpgpu_perf_t *perf, u32 runs)
{
    const size_t width = perf_name_width();
    const u64 *g = perf->global;
    const u64 kernel = g[GPGPU_PERF_KERNEL_CYCLES];
    const u32 khz = gpu_read(GPGPU_REG_INFO_CLOCK);
    char digits[21];
    u32 failed;

    xil_printf("Perf report: %u run%s, %s cycles", (unsigned int)runs, runs == 1U ? "" : "s",
               perf_u64(kernel, digits));
    if (runs != 0U && khz != 0U)
        xil_printf(", %s us of GPU time per run", perf_u64((kernel * 1000U) / ((u64)khz * runs), digits));
    xil_printf("\r\n");
    /* One base for every percentage: the run's cycles. A warp's lines and the
     * reset and drain line, like each global partition, sum to 100%. */
    xil_printf("  Columns: name, %% of KERNEL_CYCLES (for counts of cycles), total%s\r\n",
               runs > 1U ? ", per run" : "");

    for (u32 w = 0U; w < GPGPU_WARPS_PER_SM; w++) {
        const u64 running = perf_leaf_sum(perf, w);
        u64 groups[PERF_GROUP_COUNT] = { 0U };

        for (u32 l = 0U; l < GPGPU_PERF_WARP_LEAF_COUNT; l++)
            groups[perf_leaf_group[l]] += perf->warp[w][l];
        xil_printf("  Warp %u (RUNNING is %s cycles)\r\n", (unsigned int)w, perf_u64(running, digits));
        for (u32 group = 0U; group < PERF_GROUP_COUNT; group++) {
            perf_line(PERF_LINE_INDENT, perf_group_names[group], width, groups[group], kernel, 1, runs);
            for (u32 l = 0U; l < GPGPU_PERF_WARP_LEAF_COUNT; l++)
                if (perf_leaf_group[l] == group)
                    perf_line(PERF_LEAF_INDENT, perf_leaf_names[l], width, perf->warp[w][l], kernel, 1, runs);
        }
        /* The run's cycles outside RUNNING, so the warp's lines sum to 100% */
        perf_line(PERF_LINE_INDENT, "RUN_RESET + RUN_DRAIN", width,
                  g[GPGPU_PERF_RUN_RESET] + g[GPGPU_PERF_RUN_DRAIN], kernel, 1, runs);
        perf_ratio("IPC (WARP_ISSUED / RUNNING)", perf->warp[w][GPGPU_PERF_WARP_ISSUED], running);
    }

    xil_printf("  Global counters\r\n");
    for (u32 group = 0U; group < PERF_GLOBAL_GROUP_COUNT; group++) {
        perf_pad(0U, PERF_LINE_INDENT);
        xil_printf("%s\r\n", perf_global_group_names[group]);
        for (u32 c = 0U; c < GPGPU_PERF_GLOBAL_COUNT; c++) {
            if (perf_global_group_of[c] != group)
                continue;
            const int cycles = perf_global_kind[c] == GPGPU_PERF_KIND_TOTAL ||
                               perf_global_kind[c] == GPGPU_PERF_KIND_LEAF;
            perf_line(PERF_LEAF_INDENT, perf_global_names[c], width, g[c], kernel, cycles, runs);
        }
        perf_derived(group, g, khz);
    }

    failed = perf_check(perf);
    if (failed == 0U)
        xil_printf("  Perf checks: all passed\r\n");
    return failed;
}
