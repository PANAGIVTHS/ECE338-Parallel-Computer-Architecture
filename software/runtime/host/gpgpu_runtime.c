/* The host runtime (gpgpu.h): module load, copies, launches and errors. The
 * same code runs on the board and on a PC; gpgpu_backend.h is the difference. */
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#include "gpgpu.h"
#include "gpgpu_backend.h"
#include "gpgpu_module.h"

/* software.runtime.launch_timeout_ms: how long a launch may run; 0 for no limit. */
#ifndef GPGPU_LAUNCH_TIMEOUT_MS
#define GPGPU_LAUNCH_TIMEOUT_MS 10000u
#endif

static gpgpu_hardware_t hardware;
static int loaded;            /* the module is in the GPU */
static int running;           /* a launch has not been waited for */
static uint32_t started_ms;   /* when it started */
static gpgpu_error_t pending; /* the error of a finished launch, not reported yet */
static int fatal;             /* every call fails until gpgpu_reset() */
static gpgpu_fault_t last_fault;

static const gpgpu_module_t *const module = &gpgpu_module_;

/* ---- Messages ---------------------------------------------------------- */

static void say(const char *format, ...) __attribute__((format(printf, 1, 2)));
static void say(const char *format, ...)
{
    va_list arguments;
    va_start(arguments, format);
    gpgpu_backend_vprintf(format, arguments);
    va_end(arguments);
}

const char *gpgpu_error_string(gpgpu_error_t error)
{
    switch (error) {
    case GPGPU_SUCCESS: return "success";
    case GPGPU_ERROR_INVALID_VALUE: return "invalid value: a bad argument, range or pointer";
    case GPGPU_ERROR_INCOMPATIBLE: return "the program was built for other hardware";
    case GPGPU_ERROR_NOT_READY: return "a kernel is running";
    case GPGPU_ERROR_FAULT: return "a kernel memory access failed";
    case GPGPU_ERROR_TIMEOUT: return "a kernel ran too long and was stopped";
    case GPGPU_ERROR_FATAL: return "the memory subsystem locked up; gpgpu_reset() is needed";
    }
    return "unknown error";
}

static const char *status_name(unsigned int code)
{
    static const char *const names[] = {"ST_OK", "ST_UNMAPPED", "ST_PERMISSION", "ST_MISALIGNED", "ST_SLVERR", "ST_DECERR"};
    return code < sizeof names / sizeof names[0] ? names[code] : "ST_?";
}

static void describe_fault(const gpgpu_fault_t *fault)
{
    if (fault->cause == GPGPU_CAUSE_NONE)
        return;
    say("  fault: PC 0x%x, lanes 0x%08x", (unsigned)fault->pc, (unsigned)fault->lanes);
    for (unsigned int code = 1; code < 8; code++)
        if (fault->kinds & (1u << (code - 1)))
            say(", %s", status_name(code));
    say("\n");
    if (fault->detail[0] != '\0')
        say("  %s\n", fault->detail);
}

/* ---- Launch state ------------------------------------------------------ */

static void record(gpgpu_backend_status_t status, const gpgpu_fault_t *fault)
{
    running = 0;
    switch (status) {
    case GPGPU_BACKEND_DONE:
        return;
    case GPGPU_BACKEND_FAULT:
        last_fault = *fault;
        pending = GPGPU_ERROR_FAULT;
        return;
    case GPGPU_BACKEND_FATAL:
        last_fault = *fault;
        fatal = 1;
        return;
    default: /* TIMEOUT */
        memset(&last_fault, 0, sizeof last_fault);
        last_fault.cause = GPGPU_CAUSE_TIMEOUT;
        snprintf(last_fault.detail, sizeof last_fault.detail, "stopped after %u ms (software.runtime.launch_timeout_ms)",
                 (unsigned)GPGPU_LAUNCH_TIMEOUT_MS);
        if (gpgpu_backend_stop() != 0) {
            last_fault.cause = GPGPU_CAUSE_FATAL;
            snprintf(last_fault.detail, sizeof last_fault.detail, "the GPU did not stop after the timeout");
            fatal = 1;
        } else {
            pending = GPGPU_ERROR_TIMEOUT;
        }
        return;
    }
}

/* Wait for the running launch, then report its error once. */
static gpgpu_error_t settle(void)
{
    if (!fatal && running) {
        uint32_t remaining = 0;
        if (GPGPU_LAUNCH_TIMEOUT_MS != 0) {
            uint32_t elapsed = gpgpu_backend_time_ms() - started_ms;
            remaining = elapsed < GPGPU_LAUNCH_TIMEOUT_MS ? GPGPU_LAUNCH_TIMEOUT_MS - elapsed : 1u;
        }
        gpgpu_fault_t fault;
        memset(&fault, 0, sizeof fault);
        record(gpgpu_backend_wait(remaining, &fault), &fault);
    }
    if (fatal)
        return GPGPU_ERROR_FATAL;
    gpgpu_error_t error = pending;
    pending = GPGPU_SUCCESS;
    return error;
}

gpgpu_error_t gpgpu_synchronize(void)
{
    return settle();
}

gpgpu_error_t gpgpu_query(void)
{
    if (fatal)
        return GPGPU_ERROR_FATAL;
    if (!running)
        return GPGPU_SUCCESS;
    gpgpu_fault_t fault;
    memset(&fault, 0, sizeof fault);
    gpgpu_backend_status_t status = gpgpu_backend_poll(&fault);
    if (status == GPGPU_BACKEND_RUNNING)
        return GPGPU_ERROR_NOT_READY;
    record(status, &fault);
    return fatal ? GPGPU_ERROR_FATAL : GPGPU_SUCCESS;
}

gpgpu_error_t gpgpu_get_fault(gpgpu_fault_t *fault)
{
    if (fault == NULL)
        return GPGPU_ERROR_INVALID_VALUE;
    *fault = last_fault;
    return GPGPU_SUCCESS;
}

/* ---- Module ------------------------------------------------------------ */

static int check_hardware(const char *what, uint32_t built, uint32_t found)
{
    if (built == found)
        return 0;
    say("gpgpu: %s: the program was built for %u (0x%x), the hardware has %u (0x%x)\n", what, (unsigned)built,
        (unsigned)built, (unsigned)found, (unsigned)found);
    return 1;
}

static void *device_pointer(uint32_t address)
{
    return (void *)(uintptr_t)address;
}

static gpgpu_error_t load_module(void)
{
    int differ = check_hardware("lanes", module->num_cores, hardware.lanes) |
                 check_hardware("IMEM words", module->imem_words, hardware.imem_words) |
                 check_hardware("shared memory bytes", module->shared_bytes, hardware.shared_bytes) |
                 check_hardware("GMEM base", module->gmem_base, hardware.gmem_base) |
                 check_hardware("GMEM size", module->gmem_size, hardware.gmem_size) |
                 check_hardware("FB0 base", module->fb_base[0], hardware.fb_base[0]) |
                 check_hardware("FB1 base", module->fb_base[1], hardware.fb_base[1]) |
                 check_hardware("ABI version", module->abi_version, GPGPU_ABI_VERSION);
    if (differ || module->imem_count > module->imem_words)
        return GPGPU_ERROR_INCOMPATIBLE;

    gpgpu_backend_write_imem(0, module->imem, module->imem_count);
    void *launch = device_pointer(module->launch_block);
    memset(launch, 0, GPGPU_LAUNCH_BYTES);
    gpgpu_backend_flush(launch, GPGPU_LAUNCH_BYTES);
    if (module->gmem_image_words != 0) {
        void *image = device_pointer(module->gmem_image_base);
        memcpy(image, module->gmem_image, 4u * module->gmem_image_words);
        gpgpu_backend_flush(image, 4u * module->gmem_image_words);
    }
    if (module->bss_end > module->bss_start) {
        void *bss = device_pointer(module->bss_start);
        memset(bss, 0, module->bss_end - module->bss_start);
        gpgpu_backend_flush(bss, module->bss_end - module->bss_start);
    }
    loaded = 1;
    return GPGPU_SUCCESS;
}

gpgpu_error_t gpgpu_module_reload(void)
{
    gpgpu_error_t error = settle();
    return error != GPGPU_SUCCESS ? error : load_module();
}

gpgpu_error_t gpgpu_reset(void)
{
    if (gpgpu_backend_reset() != 0)
        return GPGPU_ERROR_FATAL;
    running = 0;
    fatal = 0;
    pending = GPGPU_SUCCESS;
    memset(&last_fault, 0, sizeof last_fault);
    return load_module();
}

gpgpu_error_t gpgpu_get_properties(gpgpu_properties_t *properties)
{
    if (properties == NULL)
        return GPGPU_ERROR_INVALID_VALUE;
    properties->backend = hardware.name;
    properties->lanes = hardware.lanes;
    properties->clock_khz = hardware.clock_khz;
    properties->imem_bytes = 4u * hardware.imem_words;
    properties->shared_bytes = hardware.shared_bytes;
    properties->gmem_base = hardware.gmem_base;
    properties->gmem_bytes = hardware.gmem_size;
    properties->build_id = hardware.build_id;
    return GPGPU_SUCCESS;
}

/* ---- Memory ------------------------------------------------------------ */

static int inside(uint64_t start, uint64_t bytes, uint64_t base, uint64_t size)
{
    return start >= base && start + bytes <= base + size;
}

/* A device range: the program's data in GMEM, or a framebuffer. */
static int device_range(const void *pointer, size_t bytes)
{
    uint64_t start = (uint64_t)(uintptr_t)pointer;
    return inside(start, bytes, module->data_start, module->data_end - module->data_start) ||
           inside(start, bytes, module->fb_base[0], module->fb_size) ||
           inside(start, bytes, module->fb_base[1], module->fb_size);
}

gpgpu_error_t gpgpu_memcpy(void *dst, const void *src, size_t bytes, gpgpu_memcpy_kind_t kind)
{
    gpgpu_error_t error = settle();
    if (error != GPGPU_SUCCESS)
        return error;
    if (bytes == 0)
        return GPGPU_SUCCESS;
    if (dst == NULL || src == NULL)
        return GPGPU_ERROR_INVALID_VALUE;
    switch (kind) {
    case GPGPU_HOST_TO_DEVICE:
        if (!device_range(dst, bytes))
            return GPGPU_ERROR_INVALID_VALUE;
        /* First: a line at an unaligned end may hold neighbours the GPU has changed. */
        gpgpu_backend_invalidate(dst, bytes);
        memcpy(dst, src, bytes);
        gpgpu_backend_flush(dst, bytes);
        return GPGPU_SUCCESS;
    case GPGPU_DEVICE_TO_HOST:
        if (!device_range(src, bytes))
            return GPGPU_ERROR_INVALID_VALUE;
        gpgpu_backend_invalidate(src, bytes);
        memcpy(dst, src, bytes);
        return GPGPU_SUCCESS;
    case GPGPU_DEVICE_TO_DEVICE:
        if (!device_range(dst, bytes) || !device_range(src, bytes))
            return GPGPU_ERROR_INVALID_VALUE;
        gpgpu_backend_invalidate(src, bytes);
        gpgpu_backend_invalidate(dst, bytes);
        memmove(dst, src, bytes);
        gpgpu_backend_flush(dst, bytes);
        return GPGPU_SUCCESS;
    }
    return GPGPU_ERROR_INVALID_VALUE;
}

gpgpu_error_t gpgpu_memset(void *dst, int value, size_t bytes)
{
    gpgpu_error_t error = settle();
    if (error != GPGPU_SUCCESS)
        return error;
    if (bytes == 0)
        return GPGPU_SUCCESS;
    if (!device_range(dst, bytes))
        return GPGPU_ERROR_INVALID_VALUE;
    gpgpu_backend_invalidate(dst, bytes);
    memset(dst, value, bytes);
    gpgpu_backend_flush(dst, bytes);
    return GPGPU_SUCCESS;
}

static int symbol_span(gpgpu_symbol_t symbol, size_t bytes, size_t offset)
{
    return offset <= symbol.bytes && bytes <= symbol.bytes - offset;
}

gpgpu_error_t gpgpu_memcpy_to_symbol(gpgpu_symbol_t symbol, const void *src, size_t bytes, size_t offset)
{
    gpgpu_error_t error = settle();
    if (error != GPGPU_SUCCESS)
        return error;
    if (!symbol_span(symbol, bytes, offset))
        return GPGPU_ERROR_INVALID_VALUE;
    return gpgpu_memcpy((char *)device_pointer(symbol.address) + offset, src, bytes, GPGPU_HOST_TO_DEVICE);
}

gpgpu_error_t gpgpu_memcpy_from_symbol(void *dst, gpgpu_symbol_t symbol, size_t bytes, size_t offset)
{
    gpgpu_error_t error = settle();
    if (error != GPGPU_SUCCESS)
        return error;
    if (!symbol_span(symbol, bytes, offset))
        return GPGPU_ERROR_INVALID_VALUE;
    return gpgpu_memcpy(dst, (const char *)device_pointer(symbol.address) + offset, bytes, GPGPU_DEVICE_TO_HOST);
}

void *gpgpu_symbol_address(gpgpu_symbol_t symbol)
{
    return device_pointer(symbol.address);
}

/* ---- Launch ------------------------------------------------------------ */

gpgpu_error_t gpgpu_launch_words(uint32_t entry, gpgpu_dim3_t grid, const uint32_t *words, uint32_t count)
{
    gpgpu_error_t error = settle();
    if (error != GPGPU_SUCCESS)
        return error;
    if (!loaded || grid.x == 0 || grid.y == 0 || grid.z == 0 || grid.x > GPGPU_GRID_MAX || grid.y > GPGPU_GRID_MAX ||
        grid.z > GPGPU_GRID_MAX || count > GPGPU_LAUNCH_PARAMS || (count != 0 && words == NULL) || entry % 4 != 0 ||
        entry >= 4u * module->imem_count)
        return GPGPU_ERROR_INVALID_VALUE;

    gpgpu_launch_block_t *block = device_pointer(module->launch_block);
    gpgpu_backend_invalidate(block, sizeof *block);
    memset(block, 0, sizeof *block);
    block->entry = entry;
    block->grid_x = grid.x;
    block->grid_y = grid.y;
    block->grid_z = grid.z;
    block->abi_version = GPGPU_ABI_VERSION;
    for (uint32_t i = 0; i < count; i++)
        block->params[i] = words[i];
    gpgpu_backend_flush(block, sizeof *block);

    running = 1;
    started_ms = gpgpu_backend_time_ms();
    gpgpu_backend_start(GPGPU_LAUNCH_TIMEOUT_MS);
    return GPGPU_SUCCESS;
}

/* ---- Display, console, time -------------------------------------------- */

unsigned int *gpgpu_framebuffer(int n)
{
    return n == 0 || n == 1 ? device_pointer(module->fb_base[n]) : NULL;
}

gpgpu_error_t gpgpu_display(int n)
{
    gpgpu_error_t error = settle();
    if (error != GPGPU_SUCCESS)
        return error;
    if (n != 0 && n != 1)
        return GPGPU_ERROR_INVALID_VALUE;
    gpgpu_backend_display(n);
    return GPGPU_SUCCESS;
}

int gpgpu_key(void)
{
    return gpgpu_backend_key();
}

uint32_t gpgpu_time_ms(void)
{
    return gpgpu_backend_time_ms();
}

int gpgpu_printf(const char *format, ...)
{
    va_list arguments;
    va_start(arguments, format);
    int written = gpgpu_backend_vprintf(format, arguments);
    va_end(arguments);
    return written;
}

/* ---- Start and end ----------------------------------------------------- */

void gpgpu_check_failed_(gpgpu_error_t error, const char *call, const char *file, int line)
{
    say("%s:%d: %s: %s\n", file, line, call, gpgpu_error_string(error));
    if (error == GPGPU_ERROR_FAULT || error == GPGPU_ERROR_TIMEOUT || error == GPGPU_ERROR_FATAL)
        describe_fault(&last_fault);
    say("GPGPU_EXIT 1\n");
    gpgpu_backend_exit(1);
}

int gpgpu_runtime_main_(int argc, char **argv)
{
    if (gpgpu_backend_init(&hardware) != 0) {
        say("GPGPU_EXIT 1\n");
        return 1;
    }
    gpgpu_error_t error = load_module();
    if (error != GPGPU_SUCCESS) {
        say("gpgpu: cannot load %s: %s\nGPGPU_EXIT 1\n", module->name, gpgpu_error_string(error));
        return 1;
    }
    int status = gpgpu_main(argc, argv);
    error = settle();
    if (error != GPGPU_SUCCESS) {
        say("gpgpu: the last launch failed: %s\n", gpgpu_error_string(error));
        describe_fault(&last_fault);
        if (status == 0)
            status = 1;
    }
    say("GPGPU_EXIT %d\n", status);
    return status;
}
