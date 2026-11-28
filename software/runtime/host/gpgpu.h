#ifndef GPGPU_H
#define GPGPU_H

/*
 * The host API of the GPGPU runtime (docs/runtime-spec.md, section 8).
 *
 * A program defines gpgpu_main(); the runtime owns main(), loads the
 * program's module (its kernels and their data) into the GPU first, and
 * prints `GPGPU_EXIT <status>` after gpgpu_main returns.
 *
 *   #include "gpgpu.h"
 *   #include "my_program_kernels.h"
 *
 *   int gpgpu_main(int argc, char **argv)
 *   {
 *       GPGPU_CHECK(gpgpu_memcpy_to_symbol(my_program_sym_input, data, sizeof data, 0));
 *       GPGPU_CHECK(gpgpu_launch(my_kernel, gpgpu_dim3(4), 3));
 *       GPGPU_CHECK(gpgpu_memcpy_from_symbol(result, my_program_sym_output, sizeof result, 0));
 *       return 0;
 *   }
 *
 * The same program runs on the board and, with the functional simulator, on a
 * PC. Every call except gpgpu_symbol_address, gpgpu_framebuffer,
 * gpgpu_query and gpgpu_get_properties waits for the running launch first.
 */

#include <stddef.h>
#include <stdint.h>

#include "gpgpu_types.h"

typedef enum {
    GPGPU_SUCCESS = 0,
    GPGPU_ERROR_INVALID_VALUE, /* bad argument, range or pointer; nothing happened */
    GPGPU_ERROR_INCOMPATIBLE,  /* the program was built for other hardware */
    GPGPU_ERROR_NOT_READY,     /* only from gpgpu_query: a kernel runs */
    GPGPU_ERROR_FAULT,         /* a kernel access failed; reported once, then cleared */
    GPGPU_ERROR_TIMEOUT,       /* a kernel ran too long and was stopped; reported once */
    GPGPU_ERROR_FATAL          /* the memory subsystem locked up; every call fails until gpgpu_reset() */
} gpgpu_error_t;

/* A GPGPU_DEVICE or GPGPU_CONSTANT variable, as <p>_kernels.h declares it. */
typedef struct {
    uint32_t address;
    uint32_t bytes;
} gpgpu_symbol_t;

typedef enum {
    GPGPU_HOST_TO_DEVICE,
    GPGPU_DEVICE_TO_HOST,
    GPGPU_DEVICE_TO_DEVICE
} gpgpu_memcpy_kind_t;

typedef struct {
    const char *backend;   /* "xc7z020" or "simulator" */
    uint32_t lanes;        /* threads of a block */
    uint32_t clock_khz;    /* 0 in the simulator */
    uint32_t imem_bytes;
    uint32_t shared_bytes; /* the BRAM: GPGPU_SHARED variables and the stacks */
    uint32_t gmem_base;    /* device address of GMEM */
    uint32_t gmem_bytes;
    uint32_t build_id;     /* RTL commit and dirty bit (BUILD_ID), 0 in the simulator */
} gpgpu_properties_t;

/* What stopped the last launch that failed. */
typedef enum {
    GPGPU_CAUSE_NONE = 0,
    GPGPU_CAUSE_MEMORY = 1,       /* FAULT_INFO: an access failed, see kinds and lanes */
    GPGPU_CAUSE_POSTED_WRITE = 2, /* FAULT_INFO: a DDR write failed after the store */
    GPGPU_CAUSE_FATAL = 3,        /* FAULT_INFO: the memory subsystem locked up */
    GPGPU_CAUSE_TIMEOUT = 16,     /* software.runtime.launch_timeout_ms passed */
    GPGPU_CAUSE_SIMULATOR = 17    /* the simulator cannot go on; see detail */
} gpgpu_fault_cause_t;

typedef struct {
    gpgpu_fault_cause_t cause;
    uint32_t kinds; /* bit k-1: some lane got memory status k (ST_UNMAPPED = 1, ...) */
    uint32_t lanes; /* bit i: lane i failed */
    uint32_t pc;    /* byte address of the failing instruction */
    char detail[224];
} gpgpu_fault_t;

/* ---- The program ------------------------------------------------------- */

/* Defined by the program. Its return value is the program's status: 0 is success. */
int gpgpu_main(int argc, char **argv);

/* ---- Device ------------------------------------------------------------ */

gpgpu_error_t gpgpu_get_properties(gpgpu_properties_t *properties);
gpgpu_error_t gpgpu_synchronize(void);
gpgpu_error_t gpgpu_query(void);
gpgpu_error_t gpgpu_reset(void);
/* Restore the initial values of the static globals: load the module again. */
gpgpu_error_t gpgpu_module_reload(void);
const char *gpgpu_error_string(gpgpu_error_t error);
/* The last failed launch; cause GPGPU_CAUSE_NONE if none failed. */
gpgpu_error_t gpgpu_get_fault(gpgpu_fault_t *fault);

/* ---- Memory ------------------------------------------------------------ */

/* Device ranges must lie in the program's data in GMEM or in a framebuffer. */
gpgpu_error_t gpgpu_memcpy(void *dst, const void *src, size_t bytes, gpgpu_memcpy_kind_t kind);
gpgpu_error_t gpgpu_memset(void *dst, int value, size_t bytes);
/* `bytes` from `offset` must lie inside the variable. */
gpgpu_error_t gpgpu_memcpy_to_symbol(gpgpu_symbol_t symbol, const void *src, size_t bytes, size_t offset);
gpgpu_error_t gpgpu_memcpy_from_symbol(void *dst, gpgpu_symbol_t symbol, size_t bytes, size_t offset);
/* The device pointer of a variable, for a kernel's pointer parameter. Never waits. */
void *gpgpu_symbol_address(gpgpu_symbol_t symbol);

/* Planned: gpgpu_malloc and gpgpu_free (runtime-spec section 15). */

/* ---- Launch ------------------------------------------------------------ */

/* gpgpu_launch(kernel, grid, parameters...): calls the generated
 * <kernel>_launch, which checks the number and the types of the parameters.
 * The launch returns once the kernel has started; the next call that waits
 * returns its error. */
#define gpgpu_launch(kernel, ...) kernel##_launch(__VA_ARGS__)

/* What the generated launch functions call: `count` parameter words. */
gpgpu_error_t gpgpu_launch_words(uint32_t entry, gpgpu_dim3_t grid, const uint32_t *words, uint32_t count);

/* A pointer parameter must fit the device's 32-bit addresses (the simulator's host is 64-bit). */
#define GPGPU_PARAM_TOO_WIDE_(value) \
    (__builtin_classify_type(value) == 5 && ((uint64_t)(uintptr_t)(value) >> 32) != 0)
#define GPGPU_PARAM_WORD_(value) ((uint32_t)(uintptr_t)(value))

/* ---- Display, console, time -------------------------------------------- */

/* Device pointer of framebuffer 0 or 1 (0x00RRGGBB pixels, 1280 x 720), or NULL. */
unsigned int *gpgpu_framebuffer(int n);
/* Show framebuffer n on the display from the next frame. */
gpgpu_error_t gpgpu_display(int n);
/* The next key from the console, or -1. */
int gpgpu_key(void);
uint32_t gpgpu_time_ms(void);
int gpgpu_printf(const char *format, ...) __attribute__((format(printf, 1, 2)));

/* ---- Errors ------------------------------------------------------------ */

/* Print the error, the call, its file and line, and end the program with status 1. */
#define GPGPU_CHECK(call)                                                      \
    do {                                                                       \
        gpgpu_error_t gpgpu_check_error_ = (call);                             \
        if (gpgpu_check_error_ != GPGPU_SUCCESS)                               \
            gpgpu_check_failed_(gpgpu_check_error_, #call, __FILE__, __LINE__); \
    } while (0)

void gpgpu_check_failed_(gpgpu_error_t error, const char *call, const char *file, int line)
    __attribute__((noreturn));

#endif /* GPGPU_H */
