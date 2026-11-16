#include "../gpgpu_runtime.h"
#include "doom_kernel.h"

/*
 * The GPU side of DOOM: the game's two pixel loops, R_DrawColumn and
 * R_DrawSpan, and the scaling of its 320x200 picture to the display.
 * doom_abi.h describes what the host hands over, doom_kernel.h how a lane
 * draws it; the host side is software/games/doom.
 *
 * Args:
 *   GPGPU_ARGS[0] = byte address of a doom_job_t in GMEM
 *
 * Natively, `./doom_x86 > doom.ppm` draws random columns and spans through
 * the kernel and through plain copies of DOOM's loops, and exits non-zero
 * when the two pictures differ.
 */

#ifdef __riscv

/* Not static: GPGPU_START calls it by name from assembly. */
void kernel_main(void)
{
    doom_kernel(gpgpu_thread_id(), (uintptr_t)GPGPU_ARGS[0]);
}

GPGPU_START(kernel_main)

#else

#define CORES DOOM_CORES

/*
 * The kernel on every lane, for a host that has no GPU. The lanes of the GPU
 * move together, so a column drawn over a span is drawn after it in every
 * lane. Running one lane to the end and then the next would draw lane 0's
 * sprites before lane 1's floor. This runs each batch and each span through
 * all the lanes before the next one, which gives the GPU's picture.
 */
void gpgpu_kernel_run(const uint32_t *args)
{
    const volatile doom_job_t *job = (const volatile doom_job_t *)(uintptr_t)args[0];
    uint32_t ops = job->ops;

    if (ops & DOOM_OP_RENDER) {
        const volatile doom_batch_t *batch = (const volatile doom_batch_t *)(uintptr_t)job->batch;
        const volatile doom_span_t *span = (const volatile doom_span_t *)(uintptr_t)job->span;
        volatile uint8_t *idle = (volatile uint8_t *)(uintptr_t)job->idle;

        for (uint32_t b = 0; b != job->opaque_batches; b++)
            for (unsigned int tid = 0; tid < CORES; tid++)
                doom_draw_batches(tid, batch + b, batch + b + 1, idle + tid);
        for (uint32_t s = 0; s != job->spans; s++)
            for (unsigned int tid = 0; tid < CORES; tid++)
                doom_draw_spans(tid, span + s, span + s + 1, idle + tid);
        for (uint32_t b = job->opaque_batches; b != job->batches; b++)
            for (unsigned int tid = 0; tid < CORES; tid++)
                doom_draw_batches(tid, batch + b, batch + b + 1, idle + tid);
    }
    if (ops & DOOM_OP_PRESENT)
        for (unsigned int tid = 0; tid < CORES; tid++)
            gpgpu_blit(tid, &job->present);
}

#ifndef GPGPU_NATIVE_LIB

#include <stdio.h>
#include <string.h>
#include "../gpgpu_native.h"

#define WIDTH    DOOM_SURFACE_WIDTH
#define HEIGHT   DOOM_SURFACE_HEIGHT
#define BATCHES  24u /* half before the spans, half after */
#define SPANS    64u
#define TEXTURES 16u
#define OUT_W    640u
#define OUT_H    400u

static uint32_t random_state = 0x2F6E2B1u;

static uint32_t random_below(uint32_t limit)
{
    random_state = random_state * 1664525u + 1013904223u;
    return (random_state >> 8) % limit;
}

/* DOOM's own loops, on what a batch lane and a span record hold. */
static void reference_column(uint8_t *surface, const doom_batch_t *batch, unsigned int lane)
{
    uint32_t first = batch->range[lane] & 0xFFFFu, extent = batch->range[lane] >> 16;

    if (batch->range[lane] == DOOM_RANGE_NONE)
        return;

    const uint8_t *src = (const uint8_t *)(uintptr_t)batch->src[lane];
    const uint8_t *colormap = (const uint8_t *)(uintptr_t)batch->colormap[lane];
    uint8_t *dst = surface + (batch->dst[lane] - batch->dst[0]) + first * WIDTH;
    uint32_t frac = batch->frac[lane] + first * batch->step[lane];

    for (uint32_t count = 0; count <= extent; count++) {
        *dst = colormap[src[(frac >> 16) & 127u]];
        dst += WIDTH;
        frac += batch->step[lane];
    }
}

static void reference_span(uint8_t *surface, const uint8_t *screen, const doom_span_t *span)
{
    const uint8_t *flat = (const uint8_t *)(uintptr_t)span->flat;
    const uint8_t *colormap = (const uint8_t *)(uintptr_t)span->colormap;
    uint8_t *dst = surface + ((const uint8_t *)(uintptr_t)span->dst - screen);
    uint32_t position = span->position;

    for (uint32_t count = 0; count < span->count; count++) {
        *dst++ = colormap[flat[((position >> 4) & 0x0FC0u) | (position >> 26)]];
        position += span->step;
    }
}

int main(void)
{
    uint8_t *screen = gpgpu_native_alloc(WIDTH * HEIGHT);
    uint8_t *textures = gpgpu_native_alloc(TEXTURES * 128u);
    uint8_t *flat = gpgpu_native_alloc(64u * 64u);
    uint8_t *colormaps = gpgpu_native_alloc(4u * 256u);
    uint8_t *idle = gpgpu_native_alloc(DOOM_GROUP_BYTES);
    uint32_t *palette = gpgpu_native_alloc(256u * sizeof(uint32_t));
    uint32_t *display = gpgpu_native_alloc(OUT_W * OUT_H * sizeof(uint32_t));
    doom_batch_t *batches = gpgpu_native_alloc(BATCHES * sizeof(doom_batch_t));
    doom_span_t *spans = gpgpu_native_alloc(SPANS * sizeof(doom_span_t));
    doom_job_t *job = gpgpu_native_alloc(sizeof(*job));
    static uint8_t expected[WIDTH * HEIGHT];
    uint32_t chunks = OUT_W / CORES;

    for (uint32_t i = 0; i < TEXTURES * 128u; i++)
        textures[i] = (uint8_t)(random_below(256u));
    for (uint32_t i = 0; i < 64u * 64u; i++)
        flat[i] = (uint8_t)(((i >> 6) ^ i) * 5u);
    for (uint32_t i = 0; i < 4u * 256u; i++)
        colormaps[i] = (uint8_t)((i & 255u) >> (i >> 8));
    for (uint32_t i = 0; i < 256u; i++)
        palette[i] = (i << 16) | (i << 8) | (255u - i);

    /* Each batch: CORES neighbouring columns, so no two share a pixel; a
     * few lanes left empty; tops and heights at random. */
    for (uint32_t b = 0; b < BATCHES; b++) {
        doom_batch_t *batch = &batches[b];
        uint32_t x0 = random_below(WIDTH - CORES + 1u);
        uint32_t top = random_below(HEIGHT - 8u);
        uint32_t rows = 1u + random_below(HEIGHT - top);

        batch->rows = rows;
        for (uint32_t lane = 0; lane < DOOM_LANES; lane++) {
            uint32_t first = random_below(rows);
            uint32_t extent = random_below(rows - first);

            /* Lane 0 always draws: the reference finds the batch's top through it. */
            batch->dst[lane] = gpgpu_native_address(screen) + top * WIDTH + x0 + (lane < CORES ? lane : 0u);
            batch->src[lane] = gpgpu_native_address(textures) + random_below(TEXTURES) * 128u;
            batch->colormap[lane] = gpgpu_native_address(colormaps) + random_below(4u) * 256u;
            batch->step[lane] = 0x4000u + random_below(0x30000u);
            batch->frac[lane] = random_below(0x800000u) - first * batch->step[lane];
            batch->range[lane] = (lane != 0 && (lane >= CORES || random_below(8u) == 0))
                                     ? DOOM_RANGE_NONE : DOOM_RANGE(first, extent);
        }
    }
    for (uint32_t s = 0; s < SPANS; s++) {
        uint32_t y = random_below(HEIGHT), x1 = random_below(WIDTH);

        spans[s] = (doom_span_t){
            .position = random_below(0x10000u) << 16 | random_below(0x10000u),
            .step = random_below(0x400u) << 16 | random_below(0x400u),
            .flat = gpgpu_native_address(flat), .colormap = gpgpu_native_address(colormaps),
            .dst = gpgpu_native_address(screen) + y * WIDTH + x1,
            .count = 1u + random_below(WIDTH - x1),
        };
    }

    *job = (doom_job_t){
        .ops = DOOM_OP_RENDER | DOOM_OP_PRESENT,
        .batch = gpgpu_native_address(batches), .opaque_batches = BATCHES / 2u, .batches = BATCHES,
        .span = gpgpu_native_address(spans), .spans = SPANS,
        .idle = gpgpu_native_address(idle),
        .present = {
            .src = gpgpu_native_address(screen), .src_stride = WIDTH,
            .palette = gpgpu_native_address(palette),
            .dst = gpgpu_native_address(display), .dst_stride = OUT_W * 4u,
            .dst_chunks = chunks, .dst_rows = OUT_H,
            .x_step = GPGPU_BLIT_STEP(WIDTH, OUT_W), .y_step = GPGPU_BLIT_STEP(HEIGHT, OUT_H),
        },
    };

    /* The reference: the same order, one call at a time. */
    for (uint32_t b = 0; b < BATCHES / 2u; b++)
        for (unsigned int lane = 0; lane < DOOM_LANES; lane++)
            reference_column(expected + (batches[b].dst[0] - gpgpu_native_address(screen)), &batches[b], lane);
    for (uint32_t s = 0; s < SPANS; s++)
        reference_span(expected, screen, &spans[s]);
    for (uint32_t b = BATCHES / 2u; b < BATCHES; b++)
        for (unsigned int lane = 0; lane < DOOM_LANES; lane++)
            reference_column(expected + (batches[b].dst[0] - gpgpu_native_address(screen)), &batches[b], lane);

    uint32_t arguments[1] = { gpgpu_native_address(job) };

    gpgpu_kernel_run(arguments);

    unsigned int wrong = 0;

    for (uint32_t i = 0; i < WIDTH * HEIGHT; i++)
        wrong += screen[i] != expected[i];
    for (uint32_t y = 0; y < OUT_H; y++)
        for (uint32_t x = 0; x < chunks * CORES; x++)
            wrong += display[y * OUT_W + x] != palette[expected[(y * HEIGHT / OUT_H) * WIDTH + x * WIDTH / OUT_W]];

    printf("P6\n%u %u\n255\n", (unsigned)(chunks * CORES), (unsigned)OUT_H);
    for (uint32_t y = 0; y < OUT_H; y++) {
        for (uint32_t x = 0; x < chunks * CORES; x++) {
            uint32_t color = display[y * OUT_W + x];

            putchar((int)((color >> 16) & 0xFF));
            putchar((int)((color >> 8) & 0xFF));
            putchar((int)(color & 0xFF));
        }
    }
    if (wrong != 0)
        fprintf(stderr, "doom: %u pixels differ from DOOM's own loops\n", wrong);
    return wrong != 0;
}

#endif /* !GPGPU_NATIVE_LIB */

#endif /* !__riscv */
