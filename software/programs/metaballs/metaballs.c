#include "../gpgpu_runtime.h"
#include "../gpgpu_math.h"

#define CORES GPGPU_NUM_CORES

/*
 * Metaballs: glowing blobs drift across the screen, merge when they come
 * close and split again when they part.
 *
 * Each ball has the field max(0, R^2 - d^2)^2, zero beyond its radius R; a
 * pixel's field is the sum over the balls. The blob surface is where the
 * sum reaches FIELD_SURFACE, so two balls whose fields overlap enough grow
 * a bridge between them and become one blob.
 *
 * Lanes branch with lane 0: the loops and the ball paths depend only on the
 * arguments, and the per-pixel work is straight-line code (the max(0, .) and
 * the color clamps are sign masks, not branches). There is no divider, so
 * the ball paths use a parabolic sine and the field is scaled by shifts.
 */

#define BALLS 5

/* A ball's field (R^2 - d^2)^2 is scaled down by 2^FIELD_SHIFT, and a pixel
 * is inside a blob when the sum reaches FIELD_SURFACE: one ball of R = 128
 * alone reaches it at d = R / sqrt(2), where (R^2 - d^2)^2 = 2^26. */
#define FIELD_SHIFT 18
#define FIELD_SURFACE 256

/* Ball i: radius, and phase steps per frame of its x and y paths. */
#define BALL_RADIUS(i)  (110 + 18 * (i))
#define BALL_STEP_X(i)  (3 + 2 * (i))
#define BALL_STEP_Y(i)  (4 + (i))
#define BALL_PHASE_X(i) (205 * (i))
#define BALL_PHASE_Y(i) (389 * (i))

typedef struct {
    int x[BALLS];
    int y[BALLS];
    int r2[BALLS]; /* R^2 */
} balls_t;

/* Ball centers for `frame`: Lissajous paths around the screen center. */
INLINE void ball_positions(volatile balls_t *b, int width, int height, int frame)
{
    int ax = (width * 3) >> 3;
    int ay = (height * 3) >> 3;

#pragma GCC unroll 8
    for (int i = 0; i < BALLS; i++) {
        b->x[i] = (width >> 1) + ((ax * sine_q14(frame * BALL_STEP_X(i) + BALL_PHASE_X(i))) >> 14);
        b->y[i] = (height >> 1) + ((ay * sine_q14(frame * BALL_STEP_Y(i) + BALL_PHASE_Y(i))) >> 14);
        b->r2[i] = BALL_RADIUS(i) * BALL_RADIUS(i);
    }
}

/* One ball's field, from reach = R^2 - dy^2 (a per-row constant) and dx.
 * reach < R^2 < 2^15.5, so the square fits in 31 bits. */
INLINE int ball_field(int reach, int dx)
{
    int t = max0(reach - dx * dx);

    return (t * t) >> FIELD_SHIFT;
}

INLINE int ball_reach(int r2, int dy)
{
    return r2 - dy * dy;
}

/* Field level to color: a violet glow outside the blobs, a bright rim at
 * the surface, and magenta to gold towards the centers, with faint contour
 * bands that show the shape of the field. */
INLINE unsigned int field_color(int level, int y)
{
    int g = min255(level);                       /* glow, 0..255 outside */
    int k = max0(level - FIELD_SURFACE);         /* depth inside */
    int inside = mask_of(level >= FIELD_SURFACE); /* ~0 inside */
    int rim = mask_of(k < 12) & inside;           /* ~0 on the rim */
    int g2 = (g * g) >> 8;

    int r_out = (g2 >> 1) + (g2 >> 3);
    int g_out = g2 >> 4;
    int b_out = (y >> 4) + 24 + (g2 >> 1) + (g >> 3);

    int depth = min255(k >> 3);
    int band = mask_of((k >> 6) & 1) & 24;       /* darker every other band */

    int r_in = 255 - band;
    int g_in = 30 + ((depth * 3) >> 2) - band;
    int b_in = 150 - (depth >> 1) - (band >> 1);

    int r = select_mask(inside, r_in, r_out) | (rim & 255);
    int gg = select_mask(inside, g_in, g_out) | (rim & 255);
    int b = select_mask(inside, b_in, b_out) | (rim & 255);

    return ((unsigned int)min255(r) << 16) | ((unsigned int)min255(gg) << 8) |
           (unsigned int)min255(b);
}

#ifdef __riscv

static volatile balls_t balls;

void main(void)
{
    /*
     * Args:
     *   GPGPU_ARGS[0] = framebuffer base, byte address (GPGPU_FB0_BASE or GPGPU_FB1_BASE)
     *   GPGPU_ARGS[1] = width in pixels, a multiple of CORES
     *   GPGPU_ARGS[2] = height in pixels
     *   GPGPU_ARGS[3] = frame number; the kernel advances it, so each run
     *                   draws the next frame with no host writes in between
     *
     * Each lane's stack is only GPGPU_STACK_STRIDE bytes, too small for the
     * spills of this loop nest. So the row loop keeps only y in a register
     * across rows: the arguments are reloaded (GPGPU_ARGS is volatile) and the
     * per-frame ball table is in DMEM. Every lane writes the same table.
     */
    ball_positions(&balls, GPGPU_ARGS[1], GPGPU_ARGS[2], GPGPU_ARGS[3]);

    for (int y = 0; y < GPGPU_ARGS[2]; y++) {
        int width = GPGPU_ARGS[1];
        volatile unsigned int *row =
            (volatile unsigned int *)(uintptr_t)GPGPU_ARGS[0] + y * width;
        int reach[BALLS];
        int bx[BALLS];

#pragma GCC unroll 8
        for (int i = 0; i < BALLS; i++) {
            reach[i] = ball_reach(balls.r2[i], y - balls.y[i]);
            bx[i] = balls.x[i];
        }

        /* Each store writes CORES consecutive pixels, one DDR burst. */
        int tid = (int)gpgpu_thread_id();

        for (int x = tid; x < width + tid; x += CORES) {
            int field = 0;

#pragma GCC unroll 8
            for (int i = 0; i < BALLS; i++)
                field += ball_field(reach[i], x - bx[i]);
            row[x] = field_color(field, y);
        }
    }

    /* Every lane stores the same value. */
    GPGPU_ARGS[3] = GPGPU_ARGS[3] + 1;

    return;
}

GPGPU_START(main)

#else

#include <stdio.h>
#include <stdlib.h>

/* ./metaballs_x86 width height frame > metaballs.ppm writes that frame. */
int main(int argc, char **argv)
{
    if (argc != 4) {
        fprintf(stderr, "usage: %s width height frame\n", argv[0]);
        return 1;
    }

    int width = (int)strtol(argv[1], NULL, 0);
    int height = (int)strtol(argv[2], NULL, 0);
    int frame = (int)strtol(argv[3], NULL, 0);
    balls_t b;

    ball_positions(&b, width, height, frame);

    printf("P6\n%d %d\n255\n", width, height);
    for (int y = 0; y < height; y++) {
        for (int x = 0; x < width; x++) {
            int field = 0;

            for (int i = 0; i < BALLS; i++)
                field += ball_field(ball_reach(b.r2[i], y - b.y[i]), x - b.x[i]);

            unsigned int color = field_color(field, y);

            putchar((color >> 16) & 0xFF);
            putchar((color >> 8) & 0xFF);
            putchar(color & 0xFF);
        }
    }
    return 0;
}

#endif
