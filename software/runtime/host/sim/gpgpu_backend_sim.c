/* The runtime's backend on a PC: the functional simulator (software/runtime/sim).
 *
 * GMEM and the framebuffers are mapped at their board addresses, so the
 * device pointers of the program are the same as on the board. A launch runs
 * to its end inside gpgpu_backend_start(); the runtime waits as on the board.
 *
 * Shared memory is filled with GPGPU_SIM_SHARED_FILL before every launch: its
 * contents are undefined when a block starts, and a kernel that reads it
 * before writing it sees the pattern. With GPGPU_SIM_FRAMES set to a
 * directory, every gpgpu_display() writes the framebuffer there as a PPM file.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <time.h>

#include "gpgpu_backend.h"
#include "gpgpu_sim.h"

#define GPGPU_SIM_SHARED_FILL 0xDEADBEEFu
#define MAX_INSTRUCTIONS (1ull << 40)
#define MAX_DIVERGENT_PCS 64u

static gpgpu_sim_t *sim;
static gpgpu_sim_result_t result;
static uint64_t deadline_ms;
static uint32_t divergent[MAX_DIVERGENT_PCS], divergent_count;
static unsigned int frames;

static uint64_t now_ms(void)
{
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    return (uint64_t)now.tv_sec * 1000u + (uint64_t)now.tv_nsec / 1000000u;
}

static int out_of_time(void *context)
{
    (void)context;
    return deadline_ms != 0 && now_ms() >= deadline_ms;
}

/* The hardware follows lane 0; on the board this goes unnoticed. */
static void divergence(void *context, uint32_t pc)
{
    (void)context;
    for (uint32_t i = 0; i < divergent_count; i++)
        if (divergent[i] == pc)
            return;
    if (divergent_count < MAX_DIVERGENT_PCS)
        divergent[divergent_count++] = pc;
    fprintf(stderr, "gpgpu simulator: lanes disagree on the branch or ECALL at PC 0x%x; "
                    "the hardware follows lane 0 (no divergence yet)\n", (unsigned)pc);
}

int gpgpu_backend_init(gpgpu_hardware_t *hardware)
{
    gpgpu_sim_config_t config = gpgpu_sim_default_config();
    uint32_t low, high;
    gpgpu_sim_ddr_bounds(&config, &low, &high);
    void *ddr = mmap((void *)(uintptr_t)low, high - low, PROT_READ | PROT_WRITE,
                     MAP_PRIVATE | MAP_ANONYMOUS | MAP_NORESERVE | MAP_FIXED_NOREPLACE, -1, 0);
    if (ddr == MAP_FAILED || ddr != (void *)(uintptr_t)low) {
        fprintf(stderr, "gpgpu simulator: cannot map the device memory at 0x%08x-0x%08x: %s\n", (unsigned)low,
                (unsigned)high, strerror(errno));
        return -1;
    }
    sim = gpgpu_sim_create(&config, ddr, low, high, NULL);
    if (sim == NULL) {
        fprintf(stderr, "gpgpu simulator: out of memory\n");
        return -1;
    }
    *hardware = (gpgpu_hardware_t){
        .name = "simulator",
        .lanes = config.lanes,
        .imem_words = config.imem_words,
        .shared_bytes = 4u * config.smem_words,
        .gmem_base = config.gmem_base,
        .gmem_size = config.gmem_size,
        .fb_base = {config.fb0_base, config.fb1_base},
        .fb_size = config.fb_size,
    };
    return 0;
}

int gpgpu_backend_reset(void)
{
    memset(gpgpu_sim_smem(sim), 0, 4u * gpgpu_sim_config(sim)->smem_words);
    return 0;
}

void gpgpu_backend_write_imem(uint32_t index, const uint32_t *words, uint32_t count)
{
    uint32_t *imem = gpgpu_sim_imem(sim);
    memset(imem, 0, 4u * gpgpu_sim_config(sim)->imem_words);
    memcpy(imem + index, words, 4u * count);
}

void gpgpu_backend_flush(const void *address, size_t bytes)
{
    (void)address; /* no caches to model */
    (void)bytes;
}

void gpgpu_backend_invalidate(const void *address, size_t bytes)
{
    (void)address;
    (void)bytes;
}

void gpgpu_backend_start(uint32_t timeout_ms)
{
    const gpgpu_sim_config_t *config = gpgpu_sim_config(sim);
    uint32_t *smem = gpgpu_sim_smem(sim);
    for (uint32_t i = 0; i < config->smem_words; i++)
        smem[i] = GPGPU_SIM_SHARED_FILL;
    deadline_ms = timeout_ms != 0 ? now_ms() + timeout_ms : 0;
    gpgpu_sim_run(sim, MAX_INSTRUCTIONS, divergence, out_of_time, NULL, &result);
}

static gpgpu_backend_status_t outcome(gpgpu_fault_t *fault)
{
    switch (result.status) {
    case GPGPU_SIM_DONE:
        return GPGPU_BACKEND_DONE;
    case GPGPU_SIM_FAULT:
        memset(fault, 0, sizeof *fault);
        fault->cause = GPGPU_CAUSE_MEMORY;
        fault->kinds = result.fault_kinds;
        fault->lanes = result.fault_lanes;
        fault->pc = result.fault_pc;
        return GPGPU_BACKEND_FAULT;
    case GPGPU_SIM_ERROR:
        memset(fault, 0, sizeof *fault);
        fault->cause = GPGPU_CAUSE_SIMULATOR;
        snprintf(fault->detail, sizeof fault->detail, "simulator: %s", result.error);
        fprintf(stderr, "gpgpu %s\n", fault->detail);
        return GPGPU_BACKEND_FAULT;
    default:
        return GPGPU_BACKEND_TIMEOUT;
    }
}

gpgpu_backend_status_t gpgpu_backend_wait(uint32_t timeout_ms, gpgpu_fault_t *fault)
{
    (void)timeout_ms; /* the run already ended, within its deadline */
    return outcome(fault);
}

gpgpu_backend_status_t gpgpu_backend_poll(gpgpu_fault_t *fault)
{
    return outcome(fault);
}

int gpgpu_backend_stop(void)
{
    return 0;
}

void gpgpu_backend_display(int framebuffer)
{
    const char *directory = getenv("GPGPU_SIM_FRAMES");
    if (directory == NULL || directory[0] == '\0')
        return;
    const gpgpu_sim_config_t *config = gpgpu_sim_config(sim);
    const uint32_t width = 1280, height = config->fb_size / (4u * 1280u);
    const uint32_t *pixels = (const uint32_t *)(uintptr_t)(framebuffer ? config->fb1_base : config->fb0_base);
    char path[4096];
    snprintf(path, sizeof path, "%s/frame_%05u.ppm", directory, frames++);
    FILE *file = fopen(path, "wb");
    if (file == NULL) {
        fprintf(stderr, "gpgpu simulator: %s: %s\n", path, strerror(errno));
        return;
    }
    fprintf(file, "P6\n%u %u\n255\n", (unsigned)width, (unsigned)height);
    for (uint32_t i = 0; i < width * height; i++) {
        unsigned char rgb[3] = {(unsigned char)(pixels[i] >> 16), (unsigned char)(pixels[i] >> 8), (unsigned char)pixels[i]};
        fwrite(rgb, 1, 3, file);
    }
    fclose(file);
}

int gpgpu_backend_key(void)
{
    return -1;
}

uint32_t gpgpu_backend_time_ms(void)
{
    return (uint32_t)now_ms();
}

int gpgpu_backend_vprintf(const char *format, va_list arguments)
{
    int written = vprintf(format, arguments);
    fflush(stdout);
    return written;
}

void gpgpu_backend_exit(int status)
{
    exit(status);
}

int main(int argc, char **argv)
{
    return gpgpu_runtime_main_(argc, argv);
}
