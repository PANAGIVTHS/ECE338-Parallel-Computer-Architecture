#define _GNU_SOURCE

#include "../gp_port.h"
#include "gpgpu_platform.h"

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>

/*
 * The platform on a PC: a game runs with no board.
 *
 * The framebuffers and GMEM are mapped at the addresses they have on the
 * board, so a pointer into GMEM is the GPU's address here too, and the
 * game's code is the code that runs on the ARM. The kernel is the native
 * build of the same source the GPU runs (gpgpu_kernel_run, from
 * software/programs/<kernel>), run on every lane.
 *
 * Time is virtual: a frame takes FRAME_MS and a sleep takes what it asks,
 * so a run draws the same frames every time, whatever the PC's speed.
 *
 * Usage: <game>_sim [options] [-- game arguments]
 *   --frames N        stop after N frames (default: run until the game exits)
 *   --dump DIR        write frames to DIR/frame_NNNNN.ppm
 *   --dump-every K    only every K-th frame (default 1)
 *   --checksums       print one checksum line per frame
 *   --keys LIST       console input: FRAME:TEXT,... gives TEXT to the game
 *                     from frame FRAME on; \r is Enter, \e is Escape
 *   --capture N DIR   save the N-th run of the kernel (from 1) to DIR: its
 *                     arguments, and GMEM and the framebuffers before and
 *                     after. tools/tests/kernel_replay.py runs the GPU's
 *                     own build of the kernel on the GPGPU model from the
 *                     first and compares with the second.
 */

#define FRAME_MS 29u /* one 35 Hz game tick, rounded up */

extern void gpgpu_kernel_run(const uint32_t *args);

static const uint32_t framebuffers[] = { GPGPU_FB0_BASE, GPGPU_FB1_BASE };
static unsigned int shown;
static uint32_t now_ms = 1;
static uint32_t frame;
static uint32_t kernel_args[16];

static uint32_t frame_limit;
static const char *dump_directory;
static uint32_t dump_every = 1;
static int print_checksums;

typedef struct {
    uint32_t frame;
    const char *text;
    size_t length, sent;
} key_script_t;

static uint32_t capture_run, kernel_runs;
static const char *capture_directory;

static key_script_t scripts[64];
static unsigned int script_count;
static char **game_arguments; /* from the command line, after "--" */

static void map(uint32_t address, size_t bytes, const char *name)
{
    void *memory = mmap((void *)(uintptr_t)address, bytes, PROT_READ | PROT_WRITE,
                        MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED_NOREPLACE | MAP_NORESERVE, -1, 0);

    if (memory != (void *)(uintptr_t)address) {
        fprintf(stderr, "sim: cannot map %s at 0x%08x (%s)\n", name, (unsigned)address, strerror(errno));
        exit(2);
    }
}

void gp_port_init(void)
{
    map(GPGPU_FB0_BASE, GPGPU_FB_SIZE, "FB0");
    map(GPGPU_FB1_BASE, GPGPU_FB_SIZE, "FB1");
    map(GPGPU_GMEM_BASE, GPGPU_GMEM_SIZE, "GMEM");
}

char **gp_port_arguments(char **configured)
{
    static char *merged[64];
    unsigned int count = 0;

    for (char **argument = configured; *argument != NULL && count < 63u; argument++)
        merged[count++] = *argument;
    for (char **argument = game_arguments; argument != NULL && *argument != NULL && count < 63u; argument++)
        merged[count++] = *argument;
    merged[count] = NULL;
    return merged;
}

void gp_port_halt(int status)
{
    fflush(stdout);
    exit(status);
}

uint32_t gp_time_ms(void)
{
    return now_ms;
}

void gp_sleep_ms(uint32_t ms)
{
    now_ms += ms;
}

int gp_port_console_read(void)
{
    for (unsigned int i = 0; i < script_count; i++) {
        key_script_t *script = &scripts[i];

        if (frame >= script->frame && script->sent < script->length)
            return (unsigned char)script->text[script->sent++];
    }
    return -1;
}

void gp_port_gmem(uint8_t **base, size_t *bytes)
{
    *base = (uint8_t *)(uintptr_t)GPGPU_GMEM_BASE;
    *bytes = GPGPU_GMEM_SIZE;
}

void gp_gmem_sync(const void *pointer, size_t bytes)
{
    (void)pointer;
    (void)bytes; /* no caches between the game and the kernel here */
}

unsigned int gp_gpu_lanes(void)
{
    return GPGPU_NUM_CORES;
}

void gp_gpu_set_arg(unsigned int index, uint32_t value)
{
    if (index >= sizeof(kernel_args) / sizeof(kernel_args[0]))
        gp_fatal("kernel argument %u does not exist", index);
    kernel_args[index] = value;
}

static void capture_file(const char *name, const void *data, size_t bytes)
{
    char path[512];

    snprintf(path, sizeof(path), "%s/%s", capture_directory, name);

    FILE *file = fopen(path, "wb");

    if (file == NULL || fwrite(data, 1, bytes, file) != bytes || fclose(file) != 0) {
        fprintf(stderr, "sim: cannot write %s (%s)\n", path, strerror(errno));
        exit(2);
    }
}

/* GMEM as far as it is used, and both framebuffers. */
static void capture_memory(const char *when)
{
    char name[64];

    snprintf(name, sizeof(name), "gmem_%s.bin", when);
    capture_file(name, (const void *)(uintptr_t)GPGPU_GMEM_BASE, gp_gmem_used());
    snprintf(name, sizeof(name), "fb0_%s.bin", when);
    capture_file(name, (const void *)(uintptr_t)GPGPU_FB0_BASE, GPGPU_FB_SIZE);
    snprintf(name, sizeof(name), "fb1_%s.bin", when);
    capture_file(name, (const void *)(uintptr_t)GPGPU_FB1_BASE, GPGPU_FB_SIZE);
}

int gp_port_gpu_run(void)
{
    int capture = capture_directory != NULL && ++kernel_runs == capture_run;

    if (capture) {
        char text[32 * sizeof(kernel_args) / sizeof(kernel_args[0])];
        int length = 0;

        for (unsigned int i = 0; i < sizeof(kernel_args) / sizeof(kernel_args[0]); i++)
            length += snprintf(text + length, sizeof(text) - (size_t)length, "%08x\n", (unsigned)kernel_args[i]);
        capture_file("args.txt", text, (size_t)length);
        capture_memory("before");
    }
    gpgpu_kernel_run(kernel_args);
    if (capture) {
        capture_memory("after");
        printf("sim: captured kernel run %u (frame %u) in %s\n", (unsigned)kernel_runs, (unsigned)frame,
               capture_directory);
        fflush(stdout);
        exit(0);
    }
    return 0;
}

void gp_port_display(unsigned int *width, unsigned int *height, uint32_t *stride)
{
    *width = GPGPU_FB_WIDTH;
    *height = GPGPU_FB_HEIGHT;
    *stride = GPGPU_FB_WIDTH * 4u;
}

uint32_t gp_port_display_hidden(void)
{
    return framebuffers[shown ^ 1u];
}

static void dump_frame(const uint32_t *pixels)
{
    char path[512];

    snprintf(path, sizeof(path), "%s/frame_%05u.ppm", dump_directory, (unsigned)frame);

    FILE *file = fopen(path, "wb");

    if (file == NULL) {
        fprintf(stderr, "sim: cannot write %s (%s)\n", path, strerror(errno));
        exit(2);
    }
    fprintf(file, "P6\n%u %u\n255\n", (unsigned)GPGPU_FB_WIDTH, (unsigned)GPGPU_FB_HEIGHT);
    for (uint32_t i = 0; i < GPGPU_FB_WIDTH * GPGPU_FB_HEIGHT; i++) {
        uint8_t rgb[3] = { (uint8_t)(pixels[i] >> 16), (uint8_t)(pixels[i] >> 8), (uint8_t)pixels[i] };

        fwrite(rgb, 1, 3, file);
    }
    fclose(file);
}

void gp_display_flip(void)
{
    shown ^= 1u;

    const uint32_t *pixels = (const uint32_t *)(uintptr_t)framebuffers[shown];

    if (print_checksums) {
        uint32_t hash = 2166136261u; /* FNV-1a over the pixels */

        for (uint32_t i = 0; i < GPGPU_FB_WIDTH * GPGPU_FB_HEIGHT; i++)
            hash = (hash ^ pixels[i]) * 16777619u;
        printf("frame %u checksum %08x\n", (unsigned)frame, (unsigned)hash);
    }
    if (dump_directory != NULL && frame % dump_every == 0)
        dump_frame(pixels);

    frame++;
    now_ms += FRAME_MS;
    if (frame_limit != 0 && frame >= frame_limit) {
        fflush(stdout);
        exit(0);
    }
}

/* FRAME:TEXT,FRAME:TEXT with \r, \n, \e, \t and \\ in TEXT (changed in place). */
static void parse_keys(char *list)
{
    for (char *item = strtok(list, ","); item != NULL; item = strtok(NULL, ",")) {
        char *colon = strchr(item, ':');

        if (colon == NULL || script_count == sizeof(scripts) / sizeof(scripts[0])) {
            fprintf(stderr, "sim: --keys wants FRAME:TEXT,... (at most 64)\n");
            exit(2);
        }

        char *text = colon + 1, *out = text;

        for (char *in = text; *in != '\0'; in++) {
            if (*in == '\\' && in[1] != '\0') {
                in++;
                *out++ = *in == 'r' ? '\r' : *in == 'n' ? '\n' : *in == 'e' ? 27 : *in == 't' ? '\t' : *in;
            } else {
                *out++ = *in;
            }
        }
        scripts[script_count++] = (key_script_t){ (uint32_t)strtoul(item, NULL, 10), text, (size_t)(out - text), 0 };
    }
}

int main(int argc, char **argv)
{
    for (int i = 1; i < argc; i++) {
        const char *value = i + 1 < argc ? argv[i + 1] : NULL;

        if (strcmp(argv[i], "--") == 0) {
            game_arguments = &argv[i + 1];
            break;
        } else if (strcmp(argv[i], "--checksums") == 0) {
            print_checksums = 1;
        } else if (strcmp(argv[i], "--frames") == 0 && value != NULL) {
            frame_limit = (uint32_t)strtoul(value, NULL, 10);
            i++;
        } else if (strcmp(argv[i], "--dump") == 0 && value != NULL) {
            dump_directory = value;
            i++;
        } else if (strcmp(argv[i], "--dump-every") == 0 && value != NULL) {
            dump_every = (uint32_t)strtoul(value, NULL, 10);
            if (dump_every == 0)
                dump_every = 1;
            i++;
        } else if (strcmp(argv[i], "--keys") == 0 && value != NULL) {
            parse_keys(argv[++i]);
        } else if (strcmp(argv[i], "--capture") == 0 && i + 2 < argc) {
            capture_run = (uint32_t)strtoul(argv[i + 1], NULL, 10);
            capture_directory = argv[i + 2];
            i += 2;
        } else {
            fprintf(stderr, "usage: %s [--frames N] [--dump DIR] [--dump-every K] [--checksums] "
                            "[--keys FRAME:TEXT,...] [--capture N DIR] [-- game arguments]\n", argv[0]);
            return 2;
        }
    }
    gp_main();
}

/* No kernel image here: the kernel is linked in. */
const uint32_t gp_kernel_image[] = { 0 };
const unsigned int gp_kernel_words = 0;
const unsigned int gp_kernel_args_word = 0;
const unsigned int gp_kernel_args = sizeof(kernel_args) / sizeof(kernel_args[0]);
const unsigned int gp_kernel_lanes = GPGPU_NUM_CORES;
