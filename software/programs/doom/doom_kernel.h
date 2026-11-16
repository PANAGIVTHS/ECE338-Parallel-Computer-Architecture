#ifndef DOOM_KERNEL_H
#define DOOM_KERNEL_H

/*
 * The DOOM kernel, as one lane runs it: doom_kernel(lane id, job address).
 * doom.c wraps it for the GPU and for the host simulation.
 *
 * The GPU's rules, and how each loop keeps them:
 *
 *  - Lanes branch with lane 0. Every loop count here (batches, rows of a
 *    batch, spans, pixels of a span) is a word all lanes load from the same
 *    address. What differs per lane, whether this row is inside the lane's
 *    column or this pixel inside the span, is a mask that picks where the
 *    lane stores: its pixel, or its byte of the job's idle area.
 *  - No divider and only MUL of the M extension: the loops add and shift,
 *    as DOOM's own do. All of DOOM's fixed-point setup stays on the host.
 *  - 64 bytes of stack per lane: everything is inlined into one function,
 *    so the lane saves its registers once.
 *  - No .data or .rodata (DMEM is not loaded): no tables, and no switch
 *    that GCC could turn into a jump table.
 */

#include <stdint.h>
#include "../gpgpu_config.h"
#include "../gpgpu_math.h"
#include "../gpgpu_blit.h"
#include "doom_abi.h"

#ifdef __riscv
#pragma GCC optimize ("no-jump-tables")
#endif

#define DOOM_CORES GPGPU_NUM_CORES

_Static_assert(DOOM_CORES <= DOOM_LANES, "a batch has room for DOOM_LANES lanes");

/* Where a lane stores: `target` when `draw` is ~0, else `idle`. */
INLINE volatile uint8_t *doom_store_to(int draw, volatile uint8_t *target, volatile uint8_t *idle)
{
    uintptr_t mask = (uintptr_t)(intptr_t)draw;

    return (volatile uint8_t *)((uintptr_t)idle ^ (((uintptr_t)target ^ (uintptr_t)idle) & mask));
}

/* R_DrawColumn for the batches [batch, end): the lane's column of each. */
INLINE void doom_draw_batches(unsigned int tid, const volatile doom_batch_t *batch,
                              const volatile doom_batch_t *end, volatile uint8_t *idle)
{
    for (; batch != end; batch++) {
        uint32_t rows = batch->rows;
        volatile uint8_t *dst = (volatile uint8_t *)(uintptr_t)batch->dst[tid];
        const volatile uint8_t *src = (const volatile uint8_t *)(uintptr_t)batch->src[tid];
        const volatile uint8_t *colormap = (const volatile uint8_t *)(uintptr_t)batch->colormap[tid];
        uint32_t frac = batch->frac[tid];
        uint32_t step = batch->step[tid];
        uint32_t range = batch->range[tid];
        uint32_t first = range & 0xFFFFu;
        uint32_t extent = range >> 16;

        for (uint32_t row = 0; row != rows; row++) {
            uint8_t pixel = colormap[src[(frac >> 16) & 127u]];
            int draw = mask_of((row - first) <= extent); /* unsigned: rows before `first` wrap */

            *doom_store_to(draw, dst, idle) = pixel;
            dst += DOOM_SURFACE_WIDTH;
            frac += step;
        }
    }
}

/* R_DrawSpan for the spans [span, end): the lane's pixels of each. */
INLINE void doom_draw_spans(unsigned int tid, const volatile doom_span_t *span,
                            const volatile doom_span_t *end, volatile uint8_t *idle)
{
    for (; span != end; span++) {
        uint32_t step = span->step;
        /* The lane's first pixel is `tid` steps in. The product wraps as
         * the additions it replaces would. */
        uint32_t position = span->position + tid * step;
        uint32_t chunk_step = step * DOOM_CORES;
        const volatile uint8_t *flat = (const volatile uint8_t *)(uintptr_t)span->flat;
        const volatile uint8_t *colormap = (const volatile uint8_t *)(uintptr_t)span->colormap;
        volatile uint8_t *dst = (volatile uint8_t *)(uintptr_t)span->dst + tid;
        int count = (int)span->count;
        int left = count - (int)tid; /* > 0 while the lane's pixel is inside the span */

        for (int todo = count; todo > 0; todo -= (int)DOOM_CORES) {
            uint32_t spot = ((position >> 4) & 0x0FC0u) | (position >> 26);
            uint8_t pixel = colormap[flat[spot]];

            *doom_store_to(mask_of(left > 0), dst, idle) = pixel;
            dst += DOOM_CORES;
            position += chunk_step;
            left -= (int)DOOM_CORES;
        }
    }
}

INLINE void doom_kernel(unsigned int tid, uintptr_t job_address)
{
    const volatile doom_job_t *job = (const volatile doom_job_t *)job_address;
    uint32_t ops = job->ops;

    if (ops & DOOM_OP_RENDER) {
        const volatile doom_batch_t *batch = (const volatile doom_batch_t *)(uintptr_t)job->batch;
        uint32_t first = 0;
        uint32_t last = job->opaque_batches;

        /* Opaque batches, the spans, then the batches drawn over them. One
         * loop, so the batch code is in the image, and in a stack frame, once. */
        for (uint32_t pass = 0; pass != 2; pass++) {
            volatile uint8_t *idle = (volatile uint8_t *)(uintptr_t)job->idle + tid;

            doom_draw_batches(tid, batch + first, batch + last, idle);
            if (pass == 0) {
                const volatile doom_span_t *span = (const volatile doom_span_t *)(uintptr_t)job->span;

                doom_draw_spans(tid, span, span + job->spans, idle);
            }
            first = last;
            last = job->batches;
        }
    }
    if (ops & DOOM_OP_PRESENT)
        gpgpu_blit(tid, &job->present);
}

#endif /* DOOM_KERNEL_H */
