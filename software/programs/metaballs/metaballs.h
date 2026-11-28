#ifndef METABALLS_H
#define METABALLS_H

/* What the kernel (metaballs.c) and the host program (host.c) share: the
 * balls of a frame, their fields and the color of a pixel. */

#include "gpgpu_math.h"

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

#endif /* METABALLS_H */
