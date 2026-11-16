#include "gp_port.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <strings.h>

/*
 * The parts of the platform that are the same on the board and on a PC:
 * the console, the GMEM allocator, the built-in files, the placement of the
 * picture on the display, and main's loop.
 */

/* ---- Console ---------------------------------------------------------- */

void gp_log(const char *format, ...)
{
    va_list arguments;

    va_start(arguments, format);
    vprintf(format, arguments);
    va_end(arguments);
    fflush(stdout);
}

void gp_fatal(const char *format, ...)
{
    va_list arguments;

    printf("\r\nFATAL (%s): ", gp_game.name);
    va_start(arguments, format);
    vprintf(format, arguments);
    va_end(arguments);
    printf("\r\n");
    fflush(stdout);
    gp_port_halt(1);
}

void gp_exit(int status)
{
    gp_log("%s: exit %d\r\n", gp_game.name, status);
    gp_port_halt(status);
}

/* ---- GMEM ------------------------------------------------------------- */

/* The DDR backend's group: allocations start on one, and are kept one apart,
 * so a kernel that reads a few bytes past the end of a table stays inside. */
#define GP_GROUP 128u

static uint8_t *gmem_base;
static size_t gmem_bytes, gmem_used;

static void gmem_init(void)
{
    if (gmem_base == NULL)
        gp_port_gmem(&gmem_base, &gmem_bytes);
}

void *gp_gmem_alloc(size_t bytes)
{
    gmem_init();

    size_t rounded = ((bytes + GP_GROUP - 1u) & ~(size_t)(GP_GROUP - 1u)) + GP_GROUP;

    if (rounded < bytes || rounded > gmem_bytes - gmem_used)
        gp_fatal("GMEM is full: %lu bytes asked, %lu of %lu left", (unsigned long)bytes,
                 (unsigned long)(gmem_bytes - gmem_used), (unsigned long)gmem_bytes);

    uint8_t *block = gmem_base + gmem_used;

    gmem_used += rounded;
    memset(block, 0, rounded);
    gp_gmem_sync(block, rounded);
    return block;
}

size_t gp_gmem_used(void)
{
    return gmem_used;
}

int gp_gmem_contains(const void *pointer, size_t bytes)
{
    gmem_init();

    uintptr_t first = (uintptr_t)pointer, base = (uintptr_t)gmem_base;

    return first >= base && first - base <= gmem_bytes && bytes <= gmem_bytes - (first - base);
}

/* ---- Files built into the game ---------------------------------------- */

const gp_asset_t *gp_asset_find(const char *name)
{
    static gp_asset_t found;
    const char *slash = strrchr(name, '/');
    const char *leaf = slash != NULL ? slash + 1 : name;

    for (unsigned int i = 0; i < gp_asset_count; i++) {
        if (strcasecmp(leaf, gp_assets[i].name) == 0) {
            found = (gp_asset_t){ gp_assets[i].name, gp_assets[i].start,
                                  (size_t)(gp_assets[i].end - gp_assets[i].start) };
            return &found;
        }
    }
    return NULL;
}

/* ---- The GPU, timed --------------------------------------------------- */

static uint32_t gpu_runs, gpu_ms;

void gp_gpu_run(void)
{
    uint32_t start = gp_time_ms();

    if (gp_port_gpu_run() != 0)
        gp_fatal("the kernel did not complete");
    gpu_ms += gp_time_ms() - start;
    gpu_runs++;
}

/* ---- The display ------------------------------------------------------ */

static uint32_t present_offset; /* of the picture's first pixel in a framebuffer */

void gp_present_setup(gpgpu_blit_t *blit, const uint8_t *picture, unsigned int width, unsigned int height,
                      const uint32_t *palette)
{
    unsigned int lanes = gp_gpu_lanes();
    unsigned int display_width, display_height;
    uint32_t stride;

    gp_port_display(&display_width, &display_height, &stride);

    /* Whole chunks of one pixel per lane, starting on a chunk boundary, so
     * that every store of the blit is one burst. */
    unsigned int out_width = GP_OUTPUT_WIDTH < display_width ? GP_OUTPUT_WIDTH : display_width;
    unsigned int out_height = GP_OUTPUT_HEIGHT < display_height ? GP_OUTPUT_HEIGHT : display_height;

    out_width -= out_width % lanes;
    if (out_width == 0 || out_height == 0)
        gp_fatal("the output is %ux%u pixels: nothing to show", out_width, out_height);

    unsigned int left = (display_width - out_width) / 2u;
    unsigned int top = (display_height - out_height) / 2u;

    left -= left % lanes;

    *blit = (gpgpu_blit_t){
        .src = gp_gpu_address(picture), .src_stride = width,
        .palette = gp_gpu_address(palette),
        .dst_stride = stride, .dst_chunks = out_width / lanes, .dst_rows = out_height,
        .x_step = GPGPU_BLIT_STEP(width, out_width), .y_step = GPGPU_BLIT_STEP(height, out_height),
    };
    present_offset = top * stride + left * 4u;

    /* The last output pixel must still read inside the picture. */
    if (((uint64_t)(out_width - 1u) * blit->x_step) >> 16 >= width ||
        ((uint64_t)(out_height - 1u) * blit->y_step) >> 16 >= height)
        gp_fatal("cannot scale %ux%u to %ux%u", width, height, out_width, out_height);

    gp_log("%s: %ux%u shown as %ux%u at (%u, %u) of %ux%u\r\n", gp_game.name, width, height,
           out_width, out_height, left, top, display_width, display_height);
}

void gp_present_target(gpgpu_blit_t *blit)
{
    blit->dst = gp_port_display_hidden() + present_offset;
}

/* ---- main ------------------------------------------------------------- */

/* Frames and GPU time since the last report (software.games.platform.stats_seconds). */
static void report_statistics(void)
{
    static uint32_t report_at, frames;

    frames++;
    if (GP_STATS_SECONDS == 0)
        return;

    uint32_t now = gp_time_ms();

    if (report_at == 0)
        report_at = now + GP_STATS_SECONDS * 1000u;
    if ((int32_t)(now - report_at) < 0)
        return;

    uint32_t elapsed = GP_STATS_SECONDS * 1000u + (now - report_at);

    /* No floats: the board's printf may not have them. */
    gp_log("%s: %lu.%lu frames/s; GPU busy %lu ms per frame in %lu.%lu runs\r\n", gp_game.name,
           (unsigned long)(frames * 1000u / elapsed), (unsigned long)(frames * 10000u / elapsed % 10u),
           (unsigned long)(gpu_ms / frames), (unsigned long)(gpu_runs / frames),
           (unsigned long)(gpu_runs * 10u / frames % 10u));
    report_at = now + GP_STATS_SECONDS * 1000u;
    frames = 0;
    gpu_runs = 0;
    gpu_ms = 0;
}

void gp_main(void)
{
    static char *configured[] = GP_GAME_ARGV;
    char **arguments;
    int count = 0;

    gp_port_init();
    gp_input_init();
    arguments = gp_port_arguments(configured);
    while (arguments[count] != NULL)
        count++;

    gp_log("%s: starting on %u lanes\r\n", gp_game.name, gp_gpu_lanes());
    gp_game.init(count, arguments);
    for (;;) {
        gp_game.tick();
        report_statistics();
    }
}
