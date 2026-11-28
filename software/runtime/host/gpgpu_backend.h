#ifndef GPGPU_BACKEND_H
#define GPGPU_BACKEND_H

/* What the runtime needs from a target: the board (xc7z020/) or the
 * functional simulator (sim/). Internal to the runtime. GMEM and the
 * framebuffers are at their device addresses on both, so the runtime reaches
 * them through ordinary pointers. */

#include <stdarg.h>

#include "gpgpu.h"

typedef struct {
    const char *name;
    uint32_t lanes, imem_words, shared_bytes;
    uint32_t gmem_base, gmem_size;
    uint32_t fb_base[2], fb_size;
    uint32_t clock_khz, build_id;
} gpgpu_hardware_t;

typedef enum {
    GPGPU_BACKEND_DONE,
    GPGPU_BACKEND_FAULT,   /* see the fault */
    GPGPU_BACKEND_FATAL,   /* see the fault; needs a reset */
    GPGPU_BACKEND_TIMEOUT, /* still running when the time ran out */
    GPGPU_BACKEND_RUNNING  /* only from gpgpu_backend_poll */
} gpgpu_backend_status_t;

/* 0, or -1 after printing why. */
int gpgpu_backend_init(gpgpu_hardware_t *hardware);
int gpgpu_backend_reset(void);

/* Only while the GPU is idle. */
void gpgpu_backend_write_imem(uint32_t index, const uint32_t *words, uint32_t count);

/* Cache maintenance for device memory the host wrote or will read. */
void gpgpu_backend_flush(const void *address, size_t bytes);
void gpgpu_backend_invalidate(const void *address, size_t bytes);

/* Start the kernel at PC 0. timeout_ms is software.runtime.launch_timeout_ms (0: none). */
void gpgpu_backend_start(uint32_t timeout_ms);
/* Wait at most timeout_ms (0: until it ends). The fault is filled for FAULT and FATAL. */
gpgpu_backend_status_t gpgpu_backend_wait(uint32_t timeout_ms, gpgpu_fault_t *fault);
gpgpu_backend_status_t gpgpu_backend_poll(gpgpu_fault_t *fault);
/* Stop a running kernel; 0 when the GPU is idle again. */
int gpgpu_backend_stop(void);

void gpgpu_backend_display(int framebuffer);
int gpgpu_backend_key(void);
uint32_t gpgpu_backend_time_ms(void);
int gpgpu_backend_vprintf(const char *format, va_list arguments);
/* End the program; on the board, return to the monitor. */
void gpgpu_backend_exit(int status) __attribute__((noreturn));

/* The runtime's start: initialize, load the module, run gpgpu_main, wait for
 * the GPU and print GPGPU_EXIT. Each backend's main() calls it. */
int gpgpu_runtime_main_(int argc, char **argv);

#endif /* GPGPU_BACKEND_H */
