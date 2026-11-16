/*
 * DOOM's drawing, handed to the GPU.
 *
 * DOOM draws its 3D view with two loops: R_DrawColumn (a vertical run of a
 * wall, sprite or sky texture) and R_DrawSpan (a horizontal run of a floor
 * or ceiling). Everything before them, the BSP walk, the clipping, the
 * fixed-point setup of each run, decides what to draw and stays on the ARM.
 * The game is linked with --wrap for those loops (see game.yaml), so its
 * calls arrive here. Each call is recorded, and at the end of the view the
 * kernel (software/programs/doom) draws them all.
 *
 * Order. DOOM draws walls and floors front to back and never draws a pixel
 * of them twice, so they can be drawn in any order: this is the opaque
 * phase. Sprites and see-through walls follow, back to front, over what is
 * there: the masked phase, R_DrawMasked. The kernel draws the opaque
 * batches, then the spans, then the masked batches.
 *
 * Batches. The kernel draws up to one column per lane at a time, row by
 * row, for as many rows as the batch spans. Two things make that cheap:
 *
 *  - Columns next to each other on the screen: the stores of a row are then
 *    neighbouring bytes, one DDR burst. In the opaque phase a column goes
 *    to the batch of its strip of the screen (as many pixels wide as the GPU
 *    has lanes), in the lane of its x.
 *  - Columns of similar height: a lane whose column is shorter than the
 *    batch only waits. Each strip keeps a few batches open, so the upper
 *    walls of a doorway and its lower walls fill different ones.
 *
 * In the masked phase the order matters, so the columns fill one batch in
 * the order DOOM draws them, and a column that would touch a pixel of its
 * own batch starts the next one.
 *
 * What the kernel does not draw is drawn by DOOM's own loops on the ARM,
 * after everything recorded so far: the low-detail mode, the partial
 * invisibility effect (it reads the screen back) and recoloured sprites.
 *
 * Game arguments: -nogpu draws the view on the ARM (the kernel only scales
 * the picture); -gpustats prints what a frame costs, once a second.
 */

#include <limits.h>
#include <stdlib.h>
#include <string.h>

#include "gp.h"
#include "doom_abi.h"
#include "doom_gpu.h"

#include "doomdef.h"
#include "doomtype.h"
#include "d_player.h"
#include "i_video.h"
#include "m_argv.h"
#include "m_fixed.h"
#include "r_data.h"
#include "r_draw.h"
#include "r_main.h"
#include "z_zone.h"

/* The game's own functions, behind the linker's --wrap. */
void __real_R_RenderPlayerView(player_t *player);
void __real_R_DrawMasked(void);
byte *__real_R_GetColumn(int tex, int col);
void __real_R_DrawColumn(void);
void __real_R_DrawColumnLow(void);
void __real_R_DrawFuzzColumn(void);
void __real_R_DrawFuzzColumnLow(void);
void __real_R_DrawTranslatedColumn(void);
void __real_R_DrawTranslatedColumnLow(void);
void __real_R_DrawSpan(void);
void __real_R_DrawSpanLow(void);

/* r_draw.c and r_data.c: DOOM's globals that no header declares. */
extern byte *ylookup[];
extern int columnofs[];
extern int *texturewidthmask;
extern int *texturecompositesize;
extern short **texturecolumnlump;
extern byte **texturecomposite;

/* Room for one run of the kernel; more is drawn in a second run. */
#define MAX_BATCHES 256u
#define MAX_SPANS   2048u
/* Open batches per strip of the screen in the opaque phase. */
#define SLOTS       4u

/* A call of R_DrawColumn: rows top..bottom of screen column x. */
typedef struct {
    uint16_t x;
    int16_t top, bottom;
    uint32_t src, colormap;
    uint32_t frac; /* at `top` */
    uint32_t step;
} queued_column_t;

/* A batch being filled. */
typedef struct {
    uint32_t used; /* a bit per lane */
    unsigned int count;
    int top, bottom;
    queued_column_t lane[DOOM_LANES];
} open_batch_t;

static boolean enabled;      /* the kernel draws the view */
static boolean in_view;      /* inside R_RenderPlayerView */
static boolean masked_phase; /* inside R_DrawMasked */

static unsigned int lanes;
static uint8_t *screen;
static doom_job_t *job;
static doom_batch_t *batches;
static doom_span_t *spans;
static uint8_t *idle;  /* where lanes with nothing to draw store */
static uint8_t *blank; /* what lanes with no column read */
static unsigned int batch_count, opaque_count, span_count;

static open_batch_t *open_opaque; /* SLOTS per strip */
static open_batch_t open_masked;

/* The rows each screen column has in the open masked batch (as a range). */
static struct {
    uint32_t batch;
    int16_t top, bottom;
} masked_rows[SCREENWIDTH];
static uint32_t masked_batch = 1;

/* -gpustats */
static boolean statistics;
static struct {
    uint32_t frames, runs, batches, columns, spans, pixels, steps, fallbacks;
} total;

/* ---- Running the kernel ----------------------------------------------- */

/* Draw what is recorded and closed. */
static void submit(void)
{
    if (batch_count == 0 && span_count == 0)
        return;

    job->ops = DOOM_OP_RENDER;
    job->opaque_batches = opaque_count;
    job->batches = batch_count;
    job->spans = span_count;

    gp_gmem_sync(batches, batch_count * sizeof(*batches));
    gp_gmem_sync(spans, span_count * sizeof(*spans));
    gp_gmem_sync(job, sizeof(*job));
    /* What the ARM drew reaches the GPU, and what the kernel draws now is
     * what the ARM reads afterwards. */
    gp_gmem_sync(screen, SCREENWIDTH * SCREENHEIGHT);
    gp_gpu_run();

    total.runs++;
    total.batches += batch_count;
    total.spans += span_count;
    batch_count = opaque_count = span_count = 0;
}

static void close_batch(open_batch_t *open)
{
    if (open->used == 0)
        return;
    if (batch_count == MAX_BATCHES)
        submit();

    doom_batch_t *batch = &batches[batch_count++];
    unsigned int rows = (unsigned int)(open->bottom - open->top + 1);

    batch->rows = rows;
    for (unsigned int lane = 0; lane < DOOM_LANES; lane++) {
        const queued_column_t *column = &open->lane[lane];

        if (!(open->used & (1u << lane))) {
            batch->dst[lane] = gp_gpu_address(idle);
            batch->src[lane] = gp_gpu_address(blank);
            batch->colormap[lane] = gp_gpu_address(blank);
            batch->frac[lane] = 0;
            batch->step[lane] = 0;
            batch->range[lane] = DOOM_RANGE_NONE;
            continue;
        }

        uint32_t first = (uint32_t)(column->top - open->top);

        batch->dst[lane] = gp_gpu_address(screen) + (uint32_t)open->top * SCREENWIDTH + column->x;
        batch->src[lane] = column->src;
        batch->colormap[lane] = column->colormap;
        batch->frac[lane] = column->frac - first * column->step; /* at the batch's first row */
        batch->step[lane] = column->step;
        batch->range[lane] = DOOM_RANGE(first, column->bottom - column->top);
    }
    if (!masked_phase)
        opaque_count = batch_count;

    total.steps += rows;
    open->used = 0;
    open->count = 0;
}

static void close_all(void)
{
    for (unsigned int i = 0; i < (SCREENWIDTH + lanes - 1u) / lanes * SLOTS; i++)
        close_batch(&open_opaque[i]);
    close_batch(&open_masked);
    masked_batch++;
}

/* Everything recorded so far is on the screen when this returns. */
static void flush(void)
{
    close_all();
    submit();
}

/* ---- Recording columns ------------------------------------------------ */

static void add_column(open_batch_t *open, unsigned int lane, const queued_column_t *column)
{
    if (open->used == 0) {
        open->top = column->top;
        open->bottom = column->bottom;
    } else {
        if (column->top < open->top)
            open->top = column->top;
        if (column->bottom > open->bottom)
            open->bottom = column->bottom;
    }
    open->used |= 1u << lane;
    open->count++;
    open->lane[lane] = *column;
}

/* Opaque: the lane is the column's place in its strip. Of the strip's open
 * batches with that lane free, take the one that grows least, unless a new
 * batch is cheaper: a batch costs its rows, whatever its lanes do. */
static void queue_opaque(const queued_column_t *column)
{
    unsigned int lane = column->x % lanes;
    open_batch_t *slots = &open_opaque[column->x / lanes * SLOTS];
    open_batch_t *best = NULL, *empty = NULL, *fullest = &slots[0];
    int rows = column->bottom - column->top + 1, best_growth = INT_MAX;

    for (unsigned int i = 0; i < SLOTS; i++) {
        open_batch_t *open = &slots[i];

        if (open->used == 0) {
            if (empty == NULL)
                empty = open;
            continue;
        }
        if (open->count > fullest->count)
            fullest = open;
        if (open->used & (1u << lane))
            continue;

        int top = column->top < open->top ? column->top : open->top;
        int bottom = column->bottom > open->bottom ? column->bottom : open->bottom;
        int growth = (bottom - top) - (open->bottom - open->top);

        if (growth < best_growth) {
            best = open;
            best_growth = growth;
        }
    }

    if (best != NULL && (2 * best_growth <= rows || empty == NULL)) {
        add_column(best, lane, column);
    } else if (empty != NULL) {
        add_column(empty, lane, column);
    } else {
        close_batch(fullest);
        add_column(fullest, lane, column);
    }
}

/* Masked: in DOOM's order. A column that shares a pixel with one already in
 * the batch must be drawn after it: it starts the next batch. */
static void queue_masked(const queued_column_t *column)
{
    open_batch_t *open = &open_masked;
    unsigned int x = column->x;
    boolean seen = masked_rows[x].batch == masked_batch;

    if (open->count == lanes ||
        (seen && column->top <= masked_rows[x].bottom && column->bottom >= masked_rows[x].top)) {
        close_batch(open);
        masked_batch++;
        seen = false;
    }
    if (!seen) {
        masked_rows[x].batch = masked_batch;
        masked_rows[x].top = column->top;
        masked_rows[x].bottom = column->bottom;
    } else {
        if (column->top < masked_rows[x].top)
            masked_rows[x].top = column->top;
        if (column->bottom > masked_rows[x].bottom)
            masked_rows[x].bottom = column->bottom;
    }
    add_column(open, open->count, column);
}

/* ---- DOOM's drawing functions ----------------------------------------- */

/* The kernel can draw this call: it is part of the view, and what it reads
 * is where the GPU reaches it. */
static boolean recordable(const byte *texture, size_t texels, const byte *colormap)
{
    return enabled && in_view && gp_gmem_contains(texture, texels) && gp_gmem_contains(colormap, 256);
}

/* A call the kernel does not draw: DOOM's own loop, after what is recorded. */
static void draw_on_arm(void (*loop)(void))
{
    if (enabled && in_view) {
        flush();
        total.fallbacks++;
    }
    loop();
}

void __wrap_R_DrawColumn(void)
{
    if (dc_yh < dc_yl)
        return;
    if (!recordable(dc_source, 128, dc_colormap) || (unsigned)dc_x >= SCREENWIDTH || dc_yl < 0 ||
        dc_yh >= SCREENHEIGHT) {
        draw_on_arm(__real_R_DrawColumn);
        return;
    }

    /* Where DOOM's loop starts: dest = ylookup[dc_yl] + columnofs[dc_x]. */
    size_t offset = (size_t)(ylookup[dc_yl] + columnofs[dc_x] - screen);
    int top = (int)(offset / SCREENWIDTH);
    queued_column_t column = {
        .x = (uint16_t)(offset % SCREENWIDTH),
        .top = (int16_t)top,
        .bottom = (int16_t)(top + (dc_yh - dc_yl)),
        .src = gp_gpu_address(dc_source),
        .colormap = gp_gpu_address(dc_colormap),
        .frac = (uint32_t)dc_texturemid + (uint32_t)(dc_yl - centery) * (uint32_t)dc_iscale,
        .step = (uint32_t)dc_iscale,
    };

    if (column.bottom >= SCREENHEIGHT) {
        draw_on_arm(__real_R_DrawColumn);
        return;
    }
    total.columns++;
    total.pixels += (uint32_t)(dc_yh - dc_yl + 1);
    if (masked_phase)
        queue_masked(&column);
    else
        queue_opaque(&column);
}

void __wrap_R_DrawSpan(void)
{
    if (ds_x2 < ds_x1)
        return;
    if (!recordable(ds_source, 64 * 64, ds_colormap) || ds_x1 < 0 || ds_x2 >= SCREENWIDTH ||
        (unsigned)ds_y >= SCREENHEIGHT) {
        draw_on_arm(__real_R_DrawSpan);
        return;
    }
    if (span_count == MAX_SPANS)
        submit();

    /* x in the high half, y in the low half, as DOOM's loop packs them. */
    spans[span_count++] = (doom_span_t){
        .position = (((uint32_t)ds_xfrac << 10) & 0xFFFF0000u) | (((uint32_t)ds_yfrac >> 6) & 0x0000FFFFu),
        .step = (((uint32_t)ds_xstep << 10) & 0xFFFF0000u) | (((uint32_t)ds_ystep >> 6) & 0x0000FFFFu),
        .flat = gp_gpu_address(ds_source),
        .colormap = gp_gpu_address(ds_colormap),
        .dst = gp_gpu_address(ylookup[ds_y] + columnofs[ds_x1]),
        .count = (uint32_t)(ds_x2 - ds_x1 + 1),
    };
    total.pixels += (uint32_t)(ds_x2 - ds_x1 + 1);
    total.steps += ((uint32_t)(ds_x2 - ds_x1) + lanes) / lanes;
}

void __wrap_R_DrawColumnLow(void)
{
    draw_on_arm(__real_R_DrawColumnLow);
}

void __wrap_R_DrawSpanLow(void)
{
    draw_on_arm(__real_R_DrawSpanLow);
}

void __wrap_R_DrawFuzzColumn(void)
{
    draw_on_arm(__real_R_DrawFuzzColumn);
}

void __wrap_R_DrawFuzzColumnLow(void)
{
    draw_on_arm(__real_R_DrawFuzzColumnLow);
}

void __wrap_R_DrawTranslatedColumn(void)
{
    draw_on_arm(__real_R_DrawTranslatedColumn);
}

void __wrap_R_DrawTranslatedColumnLow(void)
{
    draw_on_arm(__real_R_DrawTranslatedColumnLow);
}

/*
 * A wall texture made of several patches is built in DOOM's heap the first
 * time one of its columns is asked for, and DOOM lets the heap throw it away
 * again whenever it needs room. Three changes, for a kernel that reads it
 * later in the frame:
 *
 *  - What is recorded is drawn before the texture is built. DOOM's loop
 *    reads up to 128 texels of a column whatever the texture's height, so a
 *    short column reads the heap behind it, and building a texture changes
 *    that heap. Drawn first, the recorded columns read what DOOM read. It
 *    costs a run of the kernel per texture, in the first frames of a level.
 *  - The texture is kept until the level ends, not until the heap wants it.
 *  - The GPU is shown it once, when it is built.
 */
byte *__wrap_R_GetColumn(int tex, int col)
{
    boolean builds = texturecolumnlump[tex][col & texturewidthmask[tex]] <= 0 && texturecomposite[tex] == NULL;

    if (builds && enabled && in_view)
        flush();

    byte *column = __real_R_GetColumn(tex, col);

    if (builds && texturecomposite[tex] != NULL) {
        Z_ChangeTag(texturecomposite[tex], PU_LEVEL);
        /* And the 128 texels a column at its very end can reach. */
        gp_gmem_sync(texturecomposite[tex], (size_t)texturecompositesize[tex] + 128u);
    }
    return column;
}

void __wrap_R_DrawMasked(void)
{
    if (enabled && in_view) {
        /* The opaque batches end here; what follows is drawn over them. */
        close_all();
        masked_phase = true;
    }
    __real_R_DrawMasked();
}

static void report_statistics(void)
{
    if (!statistics || total.frames < TICRATE)
        return;

    uint32_t frames = total.frames;
    /* A step of the kernel draws up to one pixel per lane. */
    uint32_t capacity = total.steps * lanes;

    gp_log("doom gpu: per frame %lu runs, %lu batches, %lu columns, %lu spans, %lu pixels in %lu steps "
           "(%lu%% of the lanes drawing), %lu calls drawn on the ARM\r\n",
           (unsigned long)(total.runs / frames), (unsigned long)(total.batches / frames),
           (unsigned long)(total.columns / frames), (unsigned long)(total.spans / frames),
           (unsigned long)(total.pixels / frames), (unsigned long)(total.steps / frames),
           (unsigned long)(capacity != 0 ? (uint64_t)total.pixels * 100u / capacity : 0),
           (unsigned long)(total.fallbacks / frames));
    memset(&total, 0, sizeof(total));
}

void __wrap_R_RenderPlayerView(player_t *player)
{
    in_view = true;
    masked_phase = false;
    __real_R_RenderPlayerView(player);
    if (enabled)
        flush();
    in_view = false;
    masked_phase = false;

    total.frames++;
    report_statistics();
}

/* ---- Set-up and the frame's end --------------------------------------- */

void doom_gpu_init(uint8_t *doom_screen, const uint32_t *palette)
{
    unsigned int strips;

    lanes = gp_gpu_lanes();
    if (lanes == 0 || lanes > DOOM_LANES)
        gp_fatal("the kernel draws with 1 to %u lanes; the GPU has %u", (unsigned)DOOM_LANES, lanes);
    strips = (SCREENWIDTH + lanes - 1u) / lanes;

    screen = doom_screen;
    job = gp_gmem_alloc(sizeof(*job));
    batches = gp_gmem_alloc(MAX_BATCHES * sizeof(*batches));
    spans = gp_gmem_alloc(MAX_SPANS * sizeof(*spans));
    idle = gp_gmem_alloc(DOOM_GROUP_BYTES);
    blank = gp_gmem_alloc(256);
    open_opaque = calloc(strips * SLOTS, sizeof(*open_opaque));
    if (open_opaque == NULL)
        gp_fatal("doom_gpu_init: out of memory");

    job->batch = gp_gpu_address(batches);
    job->span = gp_gpu_address(spans);
    job->idle = gp_gpu_address(idle);
    gp_present_setup(&job->present, screen, SCREENWIDTH, SCREENHEIGHT, palette);
    gp_gpu_set_arg(0, gp_gpu_address(job));

    enabled = !M_CheckParm("-nogpu");
    statistics = M_CheckParm("-gpustats") != 0;
    gp_log("doom: the 3D view is drawn by the %s\r\n", enabled ? "GPU" : "ARM (-nogpu)");
}

void doom_gpu_present(void)
{
    job->ops = DOOM_OP_PRESENT;
    gp_present_target(&job->present);
    gp_gmem_sync(job, sizeof(*job));
    gp_gmem_sync(screen, SCREENWIDTH * SCREENHEIGHT);
    gp_gpu_run();
    gp_display_flip();
}
