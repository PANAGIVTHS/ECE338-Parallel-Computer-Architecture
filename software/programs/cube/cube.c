#include "../gpgpu_runtime.h"
#include "../gpgpu_math.h"

#define CORES GPGPU_NUM_CORES

/*
 * A flat-shaded cube spinning about two axes, in perspective.
 *
 * Per frame, every lane does the same setup: rotate and project the 8
 * corners, keep the faces that point at the camera (at most 3, and on a
 * convex solid they never overlap, so no depth buffer is needed), shade
 * each by its normal, and build an edge table for them in DMEM. Branches in
 * the setup are fine: every lane has the same values.
 *
 * Per row, every lane turns each visible face's edges into a span of pixels
 * [xl, xl + w). Per pixel, a lane only tests its x against the 3 spans and
 * selects the color with masks, so lanes never diverge, and each store
 * writes CORES consecutive pixels (one DDR burst).
 *
 * Screen coordinates are Q4 (1/16 pixel), so the corners move smoothly. A
 * pixel belongs to a face when its center lies inside; on an edge two faces
 * share, the face whose interior is to the right takes the pixel, so shared
 * edges have no gaps and no overlap.
 */

#define ONE (1 << 14)                 /* 1.0 in Q14: the cube's half size */
#define CUBE_DISTANCE (4 * ONE)       /* camera to cube center */
#define CUBE_FOCAL 640                /* pixels per unit at distance 1 */
#define CUBE_SPIN_X 6                 /* phase units (TURN per turn) per frame */
#define CUBE_SPIN_Y 10
/* Direction to the light (camera side, upper left), unit length, Q14. */
#define LIGHT_X (-5734)
#define LIGHT_Y 9011
#define LIGHT_Z (-12452)
#define AMBIENT 56                    /* of 255 */

#define SLOTS 3                       /* visible faces at most */
#define FAR (1 << 20)                 /* beyond any pixel x */

typedef struct {
    int ty, by;  /* Q4 y of the top and bottom end; ty == by: horizontal, unused */
    int tx;      /* Q4 x of the top end */
    int slope;   /* dx / dy, Q16 */
    int left;    /* 1: the face is to the right of the edge */
} edge_t;

typedef struct {
    int face;       /* 0..5: axis face / 2, at -1 or +1 by face % 2 */
    int ymin, ymax; /* Q4; ymin == ymax: empty slot */
    int cx, cy;     /* center, Q4 */
    unsigned int color;
    edge_t e[4];
} face_t;

typedef struct {
    int c1, s1, c2, s2; /* rotation: about x by angle 1, then about y by angle 2, Q14 */
    int sx[8], sy[8];   /* projected corners, Q4 */
    face_t slot[SLOTS];
} cube_t;

typedef struct {
    int x, y, z;
} vec_t;

/* Apply the frame's rotation. Q14. */
INLINE vec_t rotate(volatile const cube_t *cube, vec_t v)
{
    vec_t r;
    int y = (v.y * cube->c1 - v.z * cube->s1) >> 14;
    int z = (v.y * cube->s1 + v.z * cube->c1) >> 14;

    r.x = (v.x * cube->c2 + z * cube->s2) >> 14;
    r.y = y;
    r.z = (z * cube->c2 - v.x * cube->s2) >> 14;
    return r;
}

INLINE int pick_axis(vec_t v, int axis)
{
    return axis == 0 ? v.x : axis == 1 ? v.y : v.z;
}

/* Corner k (0..3, in order around the face) of face f: axis f / 2 at the
 * sign f % 2, the other two axes walking (0,0) (1,0) (1,1) (0,1). Corner
 * index bit a is the coordinate on axis a (0: -1, 1: +1). */
INLINE int face_corner(int f, int k)
{
    int a = f >> 1;
    int b = a == 2 ? 0 : a + 1;
    int c = a == 0 ? 2 : a - 1;
    int bk = (k == 1) | (k == 2);
    int ck = k >> 1;

    return ((f & 1) << a) | (bk << b) | (ck << c);
}

INLINE unsigned int shade(int f, int diffuse_q14)
{
    int level = AMBIENT + (((255 - AMBIENT) * max0(diffuse_q14)) >> 14);
    int p = f * (TURN / 6);
    int r = 128 + ((127 * sine_q14(p)) >> 14);
    int g = 128 + ((127 * sine_q14(p + TURN / 3)) >> 14);
    int b = 128 + ((127 * sine_q14(p + 2 * TURN / 3)) >> 14);

    return ((unsigned int)((r * level) >> 8) << 16) | ((unsigned int)((g * level) >> 8) << 8) |
           (unsigned int)((b * level) >> 8);
}

/* The per-frame setup. Every lane computes and stores the same values.
 *
 * It runs in small phases that pass their results through the table, and
 * its loops are not unrolled, so few values are live at once: each lane's
 * stack is only GPGPU_STACK_STRIDE bytes. */
INLINE void cube_setup(volatile cube_t *cube, int width, int height, int frame)
{
    cube->c1 = cosine_q14(frame * CUBE_SPIN_X);
    cube->s1 = sine_q14(frame * CUBE_SPIN_X);
    cube->c2 = cosine_q14(frame * CUBE_SPIN_Y);
    cube->s2 = sine_q14(frame * CUBE_SPIN_Y);

    /* Project the corners. */
#pragma GCC unroll 1
    for (int v = 0; v < 8; v++) {
        vec_t p = { (v & 1) ? ONE : -ONE, (v & 2) ? ONE : -ONE, (v & 4) ? ONE : -ONE };
        vec_t r = rotate(cube, p);
        int z = r.z + CUBE_DISTANCE;

        /* 3D y points up, screen y down. */
        cube->sx[v] = (width << 3) + sdiv_uniform(16 * CUBE_FOCAL * r.x, z);
        cube->sy[v] = (height << 3) - sdiv_uniform(16 * CUBE_FOCAL * r.y, z);
    }

    /* Pick the visible faces and shade them. */
    int used = 0;

#pragma GCC unroll 1
    for (int f = 0; f < 6; f++) {
        int a = f >> 1;
        int sign = (f & 1) ? ONE : -ONE;
        vec_t axis = { a == 0 ? sign : 0, a == 1 ? sign : 0, a == 2 ? sign : 0 };
        vec_t n = rotate(cube, axis);

        /* The face plane is n . p = 1 around the center (0, 0, D): the camera
         * at the origin sees it when n.z * D < -1. */
        if (n.z * (CUBE_DISTANCE >> 14) >= -ONE)
            continue;
        cube->slot[used].face = f;
        cube->slot[used].color = shade(f, (n.x * LIGHT_X + n.y * LIGHT_Y + n.z * LIGHT_Z) >> 14);
        used++;
    }
#pragma GCC unroll 1
    for (int s = used; s < SLOTS; s++) {
        cube->slot[s].ymin = 0;
        cube->slot[s].ymax = 0;
    }

    /* Their rows and edges. */
#pragma GCC unroll 1
    for (int s = 0; s < used; s++) {
        volatile face_t *face = &cube->slot[s];
        int cx = 0, cy = 0, ymin = FAR, ymax = -FAR;

#pragma GCC unroll 1
        for (int k = 0; k < 4; k++) {
            int v = face_corner(face->face, k);
            int y = cube->sy[v];

            cx += cube->sx[v];
            cy += y;
            ymin = y < ymin ? y : ymin;
            ymax = y > ymax ? y : ymax;
        }
        face->ymin = ymin;
        face->ymax = ymax;
        face->cx = cx >> 2;
        face->cy = cy >> 2;

#pragma GCC unroll 1
        for (int k = 0; k < 4; k++) {
            int p = face_corner(face->face, k), q = face_corner(face->face, (k + 1) & 3);

            if (cube->sy[p] > cube->sy[q]) {
                int t = p;

                p = q;
                q = t;
            }

            int tx = cube->sx[p], ty = cube->sy[p];
            int dx = cube->sx[q] - tx, dy = cube->sy[q] - ty;

            face->e[k].ty = ty;
            face->e[k].by = cube->sy[q];
            face->e[k].tx = tx;
            face->e[k].slope = dy == 0 ? 0 : sdiv_uniform(dx << 16, dy);
            /* The center is right of the edge when dy (cx - tx) > dx (cy - ty). */
            face->e[k].left = dy * (face->cx - tx) - dx * (face->cy - ty) > 0;
        }
    }
}

/* Face `s`'s pixels in row `row`: [*xl, *xl + *w), w = 0 when none. The
 * values are the same in every lane, so this may branch. */
INLINE void face_span(volatile const cube_t *cube, int s, int row, int *xl, int *w)
{
    volatile const face_t *face = &cube->slot[s];
    int y = 16 * row + 8; /* the pixel centers' Q4 y */
    int lo = -FAR, hi = FAR;

    *xl = 0;
    *w = 0;
    if (y < face->ymin || y >= face->ymax)
        return;
    for (int k = 0; k < 4; k++) {
        volatile const edge_t *e = &face->e[k];

        if (y < e->ty || y >= e->by)
            continue;

        /* The edge crosses the row at Q4 x; pixel x has its center 16 x + 8
         * right of it from bound = ceil((x - 8) / 16) on. (y - ty) < dy, so
         * the product is under |dx| * 2^16. */
        int x = e->tx + (((y - e->ty) * e->slope) >> 16);
        int bound = -((8 - x) >> 4);

        if (e->left)
            lo = bound > lo ? bound : lo;
        else
            hi = bound < hi ? bound : hi;
    }
    if (lo != -FAR && hi != FAR && hi > lo) {
        *xl = lo;
        *w = hi - lo;
    }
}

INLINE unsigned int background(int y)
{
    return ((unsigned int)(8 + (y >> 5)) << 16) | (6u << 8) | (unsigned int)(20 + (y >> 4));
}

/* Inside [xl, xl + w) as one unsigned compare. */
INLINE int in_span(int x, int xl, int w)
{
    return mask_of((unsigned int)(x - xl) < (unsigned int)w);
}

#ifdef __riscv

/* Every lane writes the same values each frame. */
static volatile cube_t cube;

void main(void)
{
    /*
     * Args:
     *   GPGPU_ARGS[0] = framebuffer base, byte address (GPGPU_FB0_BASE or GPGPU_FB1_BASE)
     *   GPGPU_ARGS[1] = width in pixels, a multiple of CORES, at most 2048
     *   GPGPU_ARGS[2] = height in pixels
     *   GPGPU_ARGS[3] = frame number; the kernel advances it, so each run
     *                   draws the next frame with no host writes in between
     *
     * Each lane's stack is only GPGPU_STACK_STRIDE bytes, so the row loop
     * reloads the arguments (GPGPU_ARGS is volatile) instead of keeping them.
     */
    cube_setup(&cube, GPGPU_ARGS[1], GPGPU_ARGS[2], GPGPU_ARGS[3]);

    for (int y = 0; y < GPGPU_ARGS[2]; y++) {
        int xl[SLOTS], w[SLOTS];
        unsigned int color[SLOTS];

#pragma GCC unroll 4
        for (int s = 0; s < SLOTS; s++) {
            face_span(&cube, s, y, &xl[s], &w[s]);
            color[s] = cube.slot[s].color;
        }

        int width = GPGPU_ARGS[1];
        int tid = (int)gpgpu_thread_id();
        unsigned int bg = background(y);
        volatile unsigned int *row = (volatile unsigned int *)(uintptr_t)GPGPU_ARGS[0] + y * width;

        for (int x = tid; x < width + tid; x += CORES) {
            unsigned int c = bg;

#pragma GCC unroll 4
            for (int s = 0; s < SLOTS; s++)
                c = (unsigned int)select_mask(in_span(x, xl[s], w[s]), (int)color[s], (int)c);
            row[x] = c;
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

/* ./cube_x86 width height frame > cube.ppm writes that frame. */
int main(int argc, char **argv)
{
    if (argc != 4) {
        fprintf(stderr, "usage: %s width height frame\n", argv[0]);
        return 1;
    }

    int width = (int)strtol(argv[1], NULL, 0);
    int height = (int)strtol(argv[2], NULL, 0);
    int frame = (int)strtol(argv[3], NULL, 0);
    cube_t cube;

    cube_setup(&cube, width, height, frame);
    printf("P6\n%d %d\n255\n", width, height);
    for (int y = 0; y < height; y++) {
        int xl[SLOTS], w[SLOTS];

        for (int s = 0; s < SLOTS; s++)
            face_span(&cube, s, y, &xl[s], &w[s]);
        for (int x = 0; x < width; x++) {
            unsigned int c = background(y);

            for (int s = 0; s < SLOTS; s++)
                c = (unsigned int)select_mask(in_span(x, xl[s], w[s]), (int)cube.slot[s].color,
                                              (int)c);
            putchar((c >> 16) & 0xFF);
            putchar((c >> 8) & 0xFF);
            putchar(c & 0xFF);
        }
    }
    return 0;
}

#endif
