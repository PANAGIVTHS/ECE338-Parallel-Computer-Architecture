/* The runtime's backend on the board: the Cortex-A9 of the Zynq, with the
 * GPGPU behind AXI4-Lite (software/host/xc7z020/gpgpu_driver.c).
 *
 * The program is loaded and started by the UART monitor (gpgpu_loader.c),
 * which leaves its arguments in the boot record (gpgpu_boot.h). When
 * gpgpu_main returns, the program returns to the monitor through the record. */
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#include "gpgpu_backend.h"
#include "gpgpu_boot.h"
#include "gpgpu_display.h"
#include "gpgpu_driver.h"

#include "sleep.h"
#include "xcortexa9_config.h"
#include "xil_cache.h"
#include "xil_io.h"
#include "xiltimer.h"
#include "xparameters.h"
#include "xuartps_hw.h"

extern char inbyte(void);

static u64 counts_per_ms;

static inline u32 gpu_read(u32 offset)
{
    return Xil_In32((UINTPTR)GPGPU_BASEADDR + offset);
}

int gpgpu_backend_init(gpgpu_hardware_t *hardware)
{
    usleep(1); /* XilTimer starts the global timer on the first sleep */
    counts_per_ms = (u64)XGet_CpuFreq() / 2U / 1000U;
    if (gpgpu_init() != GPGPU_OK)
        return -1;
    const u32 info = gpu_read(GPGPU_REG_INFO), info_mem = gpu_read(GPGPU_REG_INFO_MEM);
    *hardware = (gpgpu_hardware_t){
        .name = "xc7z020",
        .lanes = info & GPGPU_INFO_SP_COUNT_MASK,
        .imem_words = (info_mem & GPGPU_INFO_MEM_IMEM_MASK) >> GPGPU_INFO_MEM_IMEM_LSB,
        .shared_bytes = 4U * (info_mem & GPGPU_INFO_MEM_DMEM_MASK),
        .gmem_base = GPGPU_GMEM_BASE,
        .gmem_size = GPGPU_GMEM_SIZE,
        .fb_base = {GPGPU_FB0_BASE, GPGPU_FB1_BASE},
        .fb_size = GPGPU_FB_SIZE,
        .clock_khz = gpu_read(GPGPU_REG_INFO_CLOCK),
        .build_id = gpu_read(GPGPU_REG_BUILD_ID),
    };
    if ((gpu_read(GPGPU_REG_INFO_FEATURES) & GPGPU_FEATURE_DDR_MASK) == 0U) {
        printf("gpgpu: the bitstream has no DDR backend: kernels cannot reach GMEM\n");
        return -1;
    }
    return 0;
}

int gpgpu_backend_reset(void)
{
    /* The PL reset also resets the VDMA: stop it first, as the monitor does. */
    u32 shown = gpgpu_display_shown();
    gpgpu_display_stop();
    int result = gpgpu_pl_reset();
    gpgpu_display_start(shown);
    return result == GPGPU_OK ? 0 : -1;
}

void gpgpu_backend_write_imem(uint32_t index, const uint32_t *words, uint32_t count)
{
    for (uint32_t i = 0; i < count; i++)
        gpgpu_write_imem(index + i, words[i]);
}

void gpgpu_backend_flush(const void *address, size_t bytes)
{
    Xil_DCacheFlushRange((INTPTR)address, (u32)bytes);
}

void gpgpu_backend_invalidate(const void *address, size_t bytes)
{
    Xil_DCacheInvalidateRange((INTPTR)address, (u32)bytes);
}

void gpgpu_backend_start(uint32_t timeout_ms)
{
    (void)timeout_ms; /* the runtime counts it while it waits */
    if (gpgpu_start() != GPGPU_OK)
        printf("gpgpu: the GPU did not start\n");
}

static gpgpu_backend_status_t outcome(gpgpu_fault_t *fault)
{
    int result = gpgpu_finish(0);
    if (result == GPGPU_OK)
        return GPGPU_BACKEND_DONE;
    u32 info, lanes, pc;
    gpgpu_read_fault(&info, &lanes, &pc);
    memset(fault, 0, sizeof *fault);
    fault->cause = (gpgpu_fault_cause_t)(info & GPGPU_FAULT_CAUSE_MASK);
    fault->kinds = (info & GPGPU_FAULT_KINDS_MASK) >> GPGPU_FAULT_KINDS_LSB;
    fault->lanes = lanes;
    fault->pc = pc;
    if (result == GPGPU_ERR_FATAL) {
        snprintf(fault->detail, sizeof fault->detail, "memory subsystem fatal error %u (FAULT_INFO 0x%08x)",
                 (unsigned)((info & GPGPU_FAULT_FATAL_MASK) >> GPGPU_FAULT_FATAL_LSB), (unsigned)info);
        return GPGPU_BACKEND_FATAL;
    }
    gpgpu_clear(); /* reported once by the runtime; the next launch may start */
    return GPGPU_BACKEND_FAULT;
}

gpgpu_backend_status_t gpgpu_backend_wait(uint32_t timeout_ms, gpgpu_fault_t *fault)
{
    const uint32_t start = gpgpu_backend_time_ms();
    while (!gpgpu_done()) {
        if (timeout_ms != 0 && gpgpu_backend_time_ms() - start >= timeout_ms)
            return GPGPU_BACKEND_TIMEOUT;
    }
    return outcome(fault);
}

gpgpu_backend_status_t gpgpu_backend_poll(gpgpu_fault_t *fault)
{
    return gpgpu_done() ? outcome(fault) : GPGPU_BACKEND_RUNNING;
}

int gpgpu_backend_stop(void)
{
    return gpgpu_stop() == GPGPU_OK ? 0 : -1;
}

void gpgpu_backend_display(int framebuffer)
{
    gpgpu_display_show((u32)framebuffer, 0);
}

int gpgpu_backend_key(void)
{
    return XUartPs_IsReceiveData(STDIN_BASEADDRESS) ? (unsigned char)inbyte() : -1;
}

uint32_t gpgpu_backend_time_ms(void)
{
    XTime now;
    XTime_GetTime(&now);
    return (uint32_t)(now / counts_per_ms);
}

int gpgpu_backend_vprintf(const char *format, va_list arguments)
{
    int written = vprintf(format, arguments);
    fflush(stdout);
    return written;
}

/* Return to the monitor with the status, or stop here when there is none. */
void gpgpu_backend_exit(int status)
{
    volatile gpgpu_boot_record_t *boot = GPGPU_BOOT_RECORD;

    fflush(stdout);
    gpgpu_shutdown();
    boot->status = status;
    Xil_DCacheFlush();
    if (boot->magic == GPGPU_BOOT_MAGIC && boot->resume != 0U)
        ((void (*)(int))(UINTPTR)boot->resume)(status);
    for (;;) {
    }
}

/* The startup code calls main() without arguments: they are in the boot record. */
int main(void)
{
    static char *argv[GPGPU_BOOT_MAX_ARGS + 1];
    static char args[GPGPU_BOOT_ARGS_BYTES];
    static char name[] = "program";
    volatile gpgpu_boot_record_t *boot = GPGPU_BOOT_RECORD;
    int argc = 0;

    if (boot->magic == GPGPU_BOOT_MAGIC && boot->argc > 0U && boot->argc <= GPGPU_BOOT_MAX_ARGS) {
        for (u32 i = 0; i < GPGPU_BOOT_ARGS_BYTES; i++)
            args[i] = boot->args[i];
        args[GPGPU_BOOT_ARGS_BYTES - 1U] = '\0';
        for (char *arg = args; argc < (int)boot->argc && arg < args + GPGPU_BOOT_ARGS_BYTES; arg += strlen(arg) + 1)
            argv[argc++] = arg;
    } else {
        argv[argc++] = name;
    }
    argv[argc] = NULL;
    gpgpu_backend_exit(gpgpu_runtime_main_(argc, argv));
}
