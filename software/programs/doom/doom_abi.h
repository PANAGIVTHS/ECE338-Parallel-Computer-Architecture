#ifndef DOOM_ABI_H
#define DOOM_ABI_H

/*
 * What the DOOM host (software/games/doom, on the ARM) hands to the DOOM
 * kernel (doom.c, on the GPU). Both sides include this file.
 *
 * The host runs the game and decides what is drawn: it walks the BSP, clips
 * the walls and finds the floor spans, as DOOM always did. Where DOOM then
 * called its two pixel loops, R_DrawColumn and R_DrawSpan, the host records
 * the call. The kernel runs those loops: 32 columns, or 32 pixels of a span,
 * at a time.
 *
 * Everything here lives in GMEM and every address is a GPU byte address.
 * The layouts follow the DDR backend, which serves one group of 128 bytes
 * per burst: a field every lane needs is 32 words in one group, so its load
 * is one burst, and a value that is the same for every lane is one word,
 * which every lane loads from the same address in one beat.
 */

#include <stdint.h>
#include "../gpgpu_blit.h"

#define DOOM_LANES        32u  /* lanes a batch has room for */
#define DOOM_GROUP_BYTES  128u /* DDRBackendPkg::GROUP_BYTES */

/* The picture the kernel draws into: DOOM's screen, one byte per pixel. */
#define DOOM_SURFACE_WIDTH  320u
#define DOOM_SURFACE_HEIGHT 200u

/*
 * A batch: up to DOOM_LANES calls of R_DrawColumn, one per lane, drawn
 * together row by row. The batch spans `rows` rows of the surface from the
 * highest top among its columns down. A lane's column covers rows
 * `first .. first + extent` of them (range = first | extent << 16); the lane
 * steps through the other rows without storing.
 *
 * The host puts columns next to each other on the screen in one batch, so
 * the 32 stores of a row are 32 bytes of one row: one burst.
 */
typedef struct {
    uint32_t rows;                 /* the same for every lane */
    uint32_t reserved[DOOM_LANES - 1];
    uint32_t dst[DOOM_LANES];      /* surface address of the lane's pixel in the batch's first row */
    uint32_t src[DOOM_LANES];      /* texture column: 128 texels, dc_source */
    uint32_t colormap[DOOM_LANES]; /* 256 bytes, dc_colormap */
    uint32_t frac[DOOM_LANES];     /* 16.16 texel of the batch's first row */
    uint32_t step[DOOM_LANES];     /* dc_iscale */
    uint32_t range[DOOM_LANES];    /* first | extent << 16, or DOOM_RANGE_NONE */
    uint32_t pad[DOOM_LANES];      /* a batch is 1 KiB */
} doom_batch_t;

/* A lane with no column: no row is ever inside its range. */
#define DOOM_RANGE_NONE   0x0000FFFFu
#define DOOM_RANGE(first, extent) ((uint32_t)(first) | ((uint32_t)(extent) << 16))

/*
 * A span: one call of R_DrawSpan. Every lane works on the same span, lane i
 * on pixels i, i + 32, ..., so a step of the kernel stores 32 neighbours.
 * `position` and `step` hold x in the high and y in the low half, as DOOM's
 * own loop packs them.
 */
typedef struct {
    uint32_t position;
    uint32_t step;
    uint32_t flat;     /* 64 x 64 texels, ds_source */
    uint32_t colormap; /* 256 bytes, ds_colormap */
    uint32_t dst;      /* surface address of the first pixel */
    uint32_t count;    /* pixels, at least 1 */
    uint32_t pad[2];   /* 32 bytes: a span never crosses a group */
} doom_span_t;

/* What one run of the kernel does. */
#define DOOM_OP_RENDER   1u /* draw the batches and the spans into the surface */
#define DOOM_OP_PRESENT  2u /* then show the surface: gpgpu_blit(present) */

/*
 * The job: GPGPU_ARGS[0] holds its address. DOOM draws walls and floors
 * first, and no pixel twice; then sprites and see-through walls over them,
 * back to front. So the kernel draws batches [0, opaque_batches), then the
 * spans, then batches [opaque_batches, batches), in that order. Two columns
 * of one batch must not share a pixel: the host starts a new batch instead.
 */
typedef struct {
    uint32_t ops;
    uint32_t batch;          /* doom_batch_t[batches] */
    uint32_t opaque_batches;
    uint32_t batches;
    uint32_t span;           /* doom_span_t[spans] */
    uint32_t spans;
    uint32_t idle;           /* DOOM_LANES bytes: where a lane with nothing to draw stores */
    uint32_t reserved;
    gpgpu_blit_t present;
} doom_job_t;

_Static_assert(sizeof(doom_batch_t) == 8 * DOOM_GROUP_BYTES, "a batch is eight groups");
_Static_assert(sizeof(doom_span_t) == 32, "a span is a quarter of a group");
_Static_assert(sizeof(doom_job_t) <= DOOM_GROUP_BYTES, "the job fits one group");

#endif /* DOOM_ABI_H */
