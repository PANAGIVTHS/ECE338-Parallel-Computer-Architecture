#include "../gpgpu_runtime.h"
#include "../gpgpu_math.h"

#ifdef __riscv
/* Each lane has 64 bytes of stack and saving the callee-saved registers
 * takes 52 of them, so main must not spill. Moving loop invariants out of
 * loops, scheduling before register allocation, PRE and GCSE all keep more
 * values live than the 27 registers hold. */
#pragma GCC optimize ("no-move-loop-invariants", "no-tree-loop-im", "no-schedule-insns", "no-tree-pre", "no-gcse")
#endif

#define CORES ((int)GPGPU_NUM_CORES)

/*
 * A low-poly landscape of flat-shaded triangles under a sky, seen from a
 * camera that flies over it: each run draws the next frame, so the frame
 * rate shows as the speed of the flight.
 *
 * The terrain is a heightfield on a grid of cells, two triangles per cell,
 * with water at sea level, sand, grass, forest, rock and snow by height,
 * shaded by a sun and faded into the sky with distance. The grid window
 * moves with the camera: vertex row 0 is NEAR cells ahead of it and row i
 * spans HALF(i) cells to each side, so the window widens with the distance
 * like the view does: 391 vertices, 342 cells, 684 triangles, of which
 * 300 to 500 face the camera on screen. The camera flies forward, sways
 * from side to side, banks into the turns and bobs up and down.
 *
 * Per frame:
 *   1. Vertex pass: every lane projects its own vertices (one row of the
 *      window per step), with a branch-free division for the perspective.
 *   2. Cell passes: every lane takes a cell, culls its back-facing triangles,
 *      shades them (light, height colors, fog) and records the screen bands
 *      and tile columns its bounding box covers.
 *   3. Bands of 8 rows, top to bottom. Each band first gathers the cells
 *      that reach it; each lane builds the list of those cells for its tile
 *      columns (tid and tid + 32) as a bit mask. Then the band's tiles of
 *      32 x 8 pixels are drawn one by one: each lane keeps its column of the
 *      tile, 8 pixels, in registers, every cell of the tile's list paints
 *      the pixels its triangles cover (edge functions, top-left rule), and
 *      each tile row is one 32-word store, one DDR burst. Every pixel is
 *      stored once per frame, so the picture never flickers.
 *
 * Hidden surfaces: the cells are recorded far to near (rows from the far
 * end; in a row, from the outer cells in to the camera's column), and a
 * tile paints its list in that order. On a heightfield seen from above, a
 * cell can only hide cells that are at least as far in both grid directions
 * from the camera's cell, so this order is exact without a depth buffer.
 *
 * The GPU's rules: lanes branch with lane 0, so every branch here depends
 * on values that are the same in every lane, and per-lane choices are masks.
 * There is no divider (MUL is the only M instruction with the right result),
 * no AUIPC (every function is inlined), only word loads and stores, nothing
 * in .data or .rodata (DMEM is not loaded), and 64 bytes of stack per lane,
 * so the state between phases lives at fixed DMEM words.
 *
 * Args:
 *   GPGPU_ARGS[0] = framebuffer base, byte address (GPGPU_FB0_BASE or GPGPU_FB1_BASE)
 *   GPGPU_ARGS[1] = width in pixels, a multiple of CORES, at most 32 * MAX_TILES
 *   GPGPU_ARGS[2] = height in pixels, a multiple of 8
 *   GPGPU_ARGS[3] = frame number; the kernel advances it, so each run
 *                   draws the next frame with no host writes in between
 */

/* ---- The window ------------------------------------------------------- */

#define ROWS      18                     /* cell rows; vertex rows 0..ROWS */
#define HALF0     5                      /* vertex row 0: cells -HALF0..HALF0 */
#define HALF_STEP 150                    /* half-width growth per row, 1/256 cell */
#define HALF(i)   (HALF0 + (((i) * HALF_STEP) >> 8))
#define NEAR      3                      /* vertex row 0, in cells ahead of the camera's row */

/* Vertices and cells of the window: sums over the rows, as constants. */
#define VROW(i)   ((i) <= ROWS ? 2 * HALF(i) + 1 : 0)
#define QROW(i)   ((i) < ROWS ? 2 * HALF(i) : 0)
#define SUM8(F, b) (F(b) + F(b + 1) + F(b + 2) + F(b + 3) + F(b + 4) + F(b + 5) + F(b + 6) + F(b + 7))
#define VERTS     (SUM8(VROW, 0) + SUM8(VROW, 8) + SUM8(VROW, 16) + SUM8(VROW, 24))
#define CELLS     (SUM8(QROW, 0) + SUM8(QROW, 8) + SUM8(QROW, 16) + SUM8(QROW, 24))

/* ---- The world: Q8, one grid cell = 256 ------------------------------ */

#define CELL      256
#define SEA       (-154)                 /* -0.6 */
#define SPEED     20                     /* forward, per frame */
#define SWAY      768                    /* side to side, +-3 cells */
#define SWAY_STEP 3                      /* phase units per frame (TURN per turn) */
#define ALTITUDE  1664                   /* 6.5 */
#define BOB       128
#define BOB_STEP  5
#define PITCH     43                     /* 15 degrees down, phase units */
#define ROLL      14                     /* banking, up to 5 degrees */
#define FOCAL     222                    /* focal length = width * FOCAL / 256: 60 degrees across */
#define ZNEAR     64                     /* nearer vertices are not drawn */

/* Light: unit vector to the sun (ahead, up, to the left), Q14. */
#define LIGHT_X   (-9904)
#define LIGHT_Y   10730
#define LIGHT_Z   7429
#define AMBIENT   72                     /* of 256 */
#define DIFFUSE   190

/* Fog from FOG_NEAR on, full at the far end of the window (NEAR + ROWS
 * cells ahead): the fraction is (z - FOG_NEAR) * FOG_SCALE / 2^16. */
#define FOG_NEAR  (11 * CELL)
#define FOG_SCALE (65536 / ((NEAR + ROWS - 11) * CELL))

/* Sky: 0x00RRGGBB, one step per band of 8 rows down to the horizon color. */
#define SKY_TOP   0x284C8Cu
#define SKY_STEP  0x030302u
#define SKY_STEPS 45
#define HORIZON   (SKY_TOP + SKY_STEPS * SKY_STEP)

/* Ground colors, 0x00RRGGBB. Heights are the sum of a triangle's three. */
#define SAND_TOP   (3 * (SEA + 70))
#define GRASS_TOP  (3 * 230)
#define FOREST_TOP (3 * 480)
#define ROCK_TOP   (3 * 700)
#define SAND      0xD2BE82u
#define GRASS     0x5A963Cu
#define FOREST    0x2D692Du
#define ROCK      0x786E64u
#define SNOW      0xEBF0F5u
#define SHALLOW   0x2A7FB0u
#define DEEP      0x0A3270u

/* ---- Screen ----------------------------------------------------------- */

#define TILE_H    8
#define MAX_TILES 40                     /* tile columns: width <= 1280 */
#define MAX_CHUNKS 3                     /* 31 cells per chunk of a band's list */

/* Vertex positions: Q2 pixels plus GUARD, 15 bits each, packed x << 16 | y.
 * A vertex is drawn from GUARD / 4 pixels left of or above the screen to
 * GUARD / 4 + 2048 pixels right of or below it; that keeps every edge
 * function product under 2^30. */
#define GUARD     8192
#define COORD_MAX 24576
#define NOT_DRAWN 0xFFFFFFFFu

/* ---- DMEM words ------------------------------------------------------- */

/* VERT and SHADE come first: below byte 2048, a load's 12-bit offset holds
 * their base, so the tile loop needs no register for it. */
#define W_VERT    20                     /* per vertex: position */
#define W_SHADE   (W_VERT + VERTS)       /* per cell: two RGB555 colors, visible bits */
#define W_BOUNDS  (W_SHADE + CELLS)      /* per cell: valid, bands, tile columns, visible */
#define W_CAND    (W_BOUNDS + CELLS)     /* MAX_CHUNKS x 32: a band's cells */
#define W_MASK    ((W_CAND + 32 * MAX_CHUNKS + 3) & ~3) /* 4 per tile, + 1: a band's lists */
#define W_DUMMY   (W_MASK + 4 * (MAX_TILES + 1)) /* 32: stores of lanes with nothing to store */
#define W_VIEW    (W_DUMMY + CORES)      /* 32: per-frame values */
#define W_ROWBAND (W_VIEW + 32)          /* 32: bands reached by each cell row */
#define W_LANEROW (W_ROWBAND + 32)       /* 32: each lane's pixel in the band's first row */
#define W_END     (W_LANEROW + CORES)

_Static_assert(W_END <= 1536, "terrain tables run into the lane stacks");
_Static_assert(4 * W_SHADE < 2048, "VERT and SHADE must start below byte 2048");
_Static_assert(W_MASK % 4 == 0, "a tile's 4 list words must be 16-byte aligned");
_Static_assert(2 * HALF(ROWS) + 1 <= CORES, "a vertex row must fit the lanes");
_Static_assert(VERTS < 1024 && CELLS < 1024, "cell list entries hold 10-bit indices");

/* Per-frame values (W_VIEW + ...). */
#define V_CX      0                      /* camera position */
#define V_CY      1
#define V_CZ      2
#define V_CPITCH  3                      /* pitch and roll cosines and sines, Q14 */
#define V_SPITCH  4
#define V_CROLL   5
#define V_SROLL   6
#define V_GX0     7                      /* grid column of the camera's cell */
#define V_GZ0     8                      /* grid row of vertex row 0 */
#define V_FOCAL4  9                      /* 4 * focal length */
#define V_HALFW4  10                     /* 4 * width / 2 + GUARD */
#define V_HALFH4  11
#define V_TILES   12
#define V_BANDS   13
#define V_BAND    14                     /* the band being drawn */
#define V_PY      15                     /* its first pixel row (Q2 with GUARD) */
#define V_ROW     16                     /* cell_shading's row, and cells done */
#define V_DONE    17

#ifdef __riscv
#define AT(word) ((volatile int *)(uintptr_t)(4u * (unsigned int)(word)))
#else
static int dmem[2048] __attribute__((aligned(16)));
#define AT(word) ((volatile int *)(dmem + (word)))
#endif

/* The lane id, read from x31 at every use: a value computed from it once
 * and kept would hold a register, or a stack slot, for the whole kernel. */
#ifdef __riscv
#define LANE() ((int)gpgpu_thread_id())
#else
static int native_lane;
#define LANE() native_lane
#endif

#define DUMMY     AT(W_DUMMY)
#define VIEW      AT(W_VIEW)
#define ROWBAND   AT(W_ROWBAND)
#define LANEROW   AT(W_LANEROW)
#define MASK      AT(W_MASK)
#define CAND      AT(W_CAND)
#define VERT      AT(W_VERT)
#define SHADE     AT(W_SHADE)
#define BOUNDS    AT(W_BOUNDS)

/* MASK words: the end of a tile's list, the end of the band (no tile). */
#define LIST_END  ((int)0x80000000u)
#define BAND_END  ((int)0xC0000000u)

/* Bit fields of a BOUNDS word: bands b0..b1, tile columns t0..t1. */
#define B_LAST    7
#define B_T0      14
#define B_T1      20
#define B_VIS1    26
#define B_VIS2    27
#define B_VALID   31

/* ---- Lane helpers ----------------------------------------------------- */

INLINE int min_int(int a, int b)
{
    return select_mask(mask_of(a < b), a, b);
}

INLINE int max_int(int a, int b)
{
    return select_mask(mask_of(a > b), a, b);
}

INLINE volatile int *select_ptr(int mask, volatile int *a, volatile int *b)
{
    intptr_t m = mask; /* pointer-wide on the native build */

    return (volatile int *)((intptr_t)b ^ (((intptr_t)a ^ (intptr_t)b) & m));
}

/* A store of a value every lane has. Lane 0 stores it; the others store to
 * their own DUMMY word, as the BRAM takes stores to one word one per cycle
 * but stores to different words two per cycle. */
INLINE void store_uniform(volatile int *p, int value)
{
    *select_ptr(mask_of(LANE() == 0), p, &DUMMY[LANE()]) = value;
}

/* A lane's store when `active`; else to its DUMMY word. */
INLINE void store_if(int active, volatile int *p, int value)
{
    *select_ptr(mask_of(active), p, &DUMMY[LANE()]) = value;
}

/* n / d for n < 2^bits, by shift and subtract with masks: the same steps in
 * every lane, whatever the values. */
INLINE unsigned int udiv_lane(unsigned int n, unsigned int d, int bits)
{
    unsigned int q = 0, r = 0;

#pragma GCC unroll 1
    for (int i = bits - 1; i >= 0; i--) {
        r = (r << 1) | ((n >> i) & 1u);
        unsigned int ge = (unsigned int)mask_of(r >= d);

        r -= d & ge;
        q = (q << 1) - ge;
    }
    return q;
}

/* n / d rounded toward zero, d > 0, |n| < 2^bits. */
INLINE int sdiv_lane(int n, int d, int bits)
{
    int s = n >> 31;
    int q = (int)udiv_lane((unsigned int)((n ^ s) - s), (unsigned int)d, bits);

    return (q ^ s) - s;
}

/* floor(sqrt(n)) for n < 2^26, bit by bit with masks. */
INLINE unsigned int isqrt_lane(unsigned int n)
{
    unsigned int root = 0, bit = 1u << 24;

#pragma GCC unroll 1
    for (int i = 0; i < 13; i++) {
        unsigned int trial = root + bit;
        unsigned int ge = (unsigned int)mask_of(n >= trial);

        n -= trial & ge;
        root = (root >> 1) + (bit & ge);
        bit >>= 2;
    }
    return root;
}

/* v, hidden from the optimizer. */
INLINE int opaque(int v)
{
    __asm__("" : "+r"(v));
    return v;
}

INLINE unsigned int hash2(int x, int z)
{
    unsigned int h = (unsigned int)x * 0x9E3779B1u ^ (unsigned int)z * 0x85EBCA77u;

    h ^= h >> 15;
    h *= 0x2C1B3C6Du;
    return h ^ (h >> 12);
}

/* ---- The world -------------------------------------------------------- */

/* Height of grid point (gx, gz), Q8: three waves of the grid coordinates. */
INLINE int terrain_height(int gx, int gz)
{
    int t1 = (sine_q14(gx * 41 + 200) * cosine_q14(gz * 37)) >> 14;
    int t2 = sine_q14(gx * 17 - gz * 23 + 500);
    int t3 = sine_q14(gx * 97 + gz * 71);

    return (t1 * 563 + t2 * 410 + t3 * 90) >> 14;
}

/* The camera of `frame`, into VIEW. Every lane stores the same values; a
 * plain store to one word from 32 lanes takes 32 cycles, fine once a frame. */
INLINE void view_setup(int width, int height, int frame)
{
    int roll = (ROLL * cosine_q14(frame * SWAY_STEP)) >> 14;
    int cx = (SWAY * sine_q14(frame * SWAY_STEP)) >> 14;
    int cz = frame * SPEED;

    VIEW[V_CX] = cx;
    VIEW[V_CY] = ALTITUDE + ((BOB * sine_q14(frame * BOB_STEP)) >> 14);
    VIEW[V_CZ] = cz;
    VIEW[V_CPITCH] = cosine_q14(PITCH);
    VIEW[V_SPITCH] = sine_q14(PITCH);
    VIEW[V_CROLL] = cosine_q14(roll);
    VIEW[V_SROLL] = sine_q14(roll);
    VIEW[V_GX0] = cx >> 8;
    VIEW[V_GZ0] = (cz >> 8) + NEAR;
    VIEW[V_FOCAL4] = (width * FOCAL) >> 6;
    VIEW[V_HALFW4] = 2 * width + GUARD;
    VIEW[V_HALFH4] = 2 * height + GUARD;
    VIEW[V_TILES] = min_int(width >> 5, MAX_TILES);
    VIEW[V_BANDS] = height >> 3;
}

/* ---- 1. Vertex pass --------------------------------------------------- */

/* Screen position of grid point (gx, gz), packed, or NOT_DRAWN. */
INLINE unsigned int project(int gx, int gz)
{
    int dx = gx * CELL - VIEW[V_CX];
    int dy = max_int(terrain_height(gx, gz), SEA) - VIEW[V_CY];
    int dz = gz * CELL - VIEW[V_CZ];
    int cp = VIEW[V_CPITCH], sp = VIEW[V_SPITCH];

    /* Pitch down about x, then roll about the view axis. */
    int yc = (dy * cp + dz * sp) >> 14;
    int zc = (dz * cp - dy * sp) >> 14;
    int cr = VIEW[V_CROLL], sr = VIEW[V_SROLL];
    int xr = (dx * cr + yc * sr) >> 14;
    int yr = (yc * cr - dx * sr) >> 14;

    int ok = mask_of(zc >= ZNEAR);
    int z = max_int(zc, ZNEAR);
    int f4 = VIEW[V_FOCAL4];
    int x = VIEW[V_HALFW4] + sdiv_lane(f4 * xr, z, 26);
    int y = VIEW[V_HALFH4] - sdiv_lane(f4 * yr, z, 26);

    ok &= mask_of((unsigned int)x < COORD_MAX) & mask_of((unsigned int)y < COORD_MAX);
    return (unsigned int)select_mask(ok, (x << 16) | y, (int)NOT_DRAWN);
}

INLINE void vertex_pass(void)
{
    int first = 0;

#pragma GCC unroll 1
    for (int i = 0; i <= ROWS; i++) {
        int half = HALF(i);
        unsigned int p = project(VIEW[V_GX0] + LANE() - half, VIEW[V_GZ0] + i);

        store_if(LANE() <= 2 * half, &VERT[first + LANE()], (int)p);
        first += 2 * half + 1;
    }
}

/* ---- 2. Cell passes --------------------------------------------------- */

/*
 * Cell (row i, column j) has v00 and v01 at its near side (vertex row i,
 * columns j and j + 1) and v10 and v11 at its far side. Its triangles in
 * screen winding: T1 = v00 v11 v01 and T2 = v00 v10 v11, front-facing when
 * the area is positive. A row's cells are recorded from first(i) on, in
 * drawing order: the cells left of the camera's from the outside in, then
 * those right of it, then its own; far rows first.
 */
INLINE int cell_column(int s, int half)
{
    return select_mask(mask_of(s < half), s - half, 2 * half - 1 - s);
}

INLINE void cell_geometry(void)
{
    int vrow = 0, done = 0;

#pragma GCC unroll 1
    for (int i = 0; i < ROWS; i++) {
        int half = HALF(i);
        int vrow1 = vrow + 2 * half + 1;
        int s = LANE() & -(LANE() < 2 * half);
        int j = cell_column(s, half);
        int a = vrow + j + half, b = vrow1 + j + HALF(i + 1);
        unsigned int p00 = (unsigned int)VERT[a], p01 = (unsigned int)VERT[a + 1];
        unsigned int p10 = (unsigned int)VERT[b], p11 = (unsigned int)VERT[b + 1];
        int drawn = ~((int)(p00 | p01 | p10 | p11) >> 31);

        int x00 = (int)(p00 >> 16), y00 = (int)(p00 & 0xFFFFu);
        int x01 = (int)(p01 >> 16), y01 = (int)(p01 & 0xFFFFu);
        int x10 = (int)(p10 >> 16), y10 = (int)(p10 & 0xFFFFu);
        int x11 = (int)(p11 >> 16), y11 = (int)(p11 & 0xFFFFu);
        int vis1 = (x11 - x00) * (y01 - y00) - (y11 - y00) * (x01 - x00) > 0;
        int vis2 = (x10 - x00) * (y11 - y00) - (y10 - y00) * (x11 - x00) > 0;

        /* Bounding box in pixels, then tile columns and bands. */
        int xmin = min_int(min_int(x00, x01), min_int(x10, x11));
        int xmax = max_int(max_int(x00, x01), max_int(x10, x11));
        int ymin = min_int(min_int(y00, y01), min_int(y10, y11));
        int ymax = max_int(max_int(y00, y01), max_int(y10, y11));
        int t0 = max_int((xmin - GUARD) >> 7, 0), t1 = min_int((xmax - GUARD) >> 7, VIEW[V_TILES] - 1);
        int b0 = max_int((ymin - GUARD) >> 5, 0), b1 = min_int((ymax - GUARD) >> 5, VIEW[V_BANDS] - 1);
        int valid = drawn & mask_of(vis1 | vis2) & mask_of(t0 <= t1) & mask_of(b0 <= b1);
        int bounds = b0 | (b1 << B_LAST) | (t0 << B_T0) | (t1 << B_T1) | (vis1 << B_VIS1) |
                     (vis2 << B_VIS2) | (int)(1u << B_VALID);

        /* The lane's values are recomputed rather than kept: registers are
         * short here, and the stack is too. */
        store_if(LANE() < 2 * half, &BOUNDS[CELLS - done - 2 * half + (LANE() & -(LANE() < 2 * half))],
                 bounds & valid);
        vrow = vrow1;
        done += 2 * half;
    }
}

INLINE unsigned int to_rgb555(unsigned int c)
{
    return ((c >> 9) & 0x7C00u) | ((c >> 6) & 0x03E0u) | ((c >> 3) & 0x001Fu);
}

/* Small masks only: every constant fits an immediate. */
INLINE unsigned int from_rgb555(unsigned int c)
{
    return (((c >> 10) & 31u) << 19) | (((c >> 5) & 31u) << 11) | ((c & 31u) << 3);
}

/* r, g, b * level / 256, each channel at most 255. */
INLINE unsigned int scale_rgb(unsigned int c, int level)
{
    int r = min255((int)((c >> 16) & 0xFFu) * level >> 8);
    int g = min255((int)((c >> 8) & 0xFFu) * level >> 8);
    int b = min255((int)(c & 0xFFu) * level >> 8);

    return ((unsigned int)r << 16) | ((unsigned int)g << 8) | (unsigned int)b;
}

/* c moved toward f by k / 256 per channel, 0 <= k <= 256. */
INLINE unsigned int mix_rgb(unsigned int c, unsigned int f, int k)
{
    int r = (int)((c >> 16) & 0xFFu), g = (int)((c >> 8) & 0xFFu), b = (int)(c & 0xFFu);

    r += (((int)((f >> 16) & 0xFFu) - r) * k) >> 8;
    g += (((int)((f >> 8) & 0xFFu) - g) * k) >> 8;
    b += (((int)(f & 0xFFu) - b) * k) >> 8;
    return ((unsigned int)r << 16) | ((unsigned int)g << 8) | (unsigned int)b;
}

/* Color of one triangle: its normal (nx, CELL, nz) lights the color its
 * height sum hs gives; raw is the lowest raw height of its corners (depth of
 * the water), zc its distance for the fog, var a per-triangle variation. */
INLINE unsigned int triangle_color(int nx, int nz, int hs, int raw, int zc, unsigned int var)
{
    int dot = max0(nx * LIGHT_X + CELL * LIGHT_Y + nz * LIGHT_Z);
    unsigned int len = isqrt_lane((unsigned int)(nx * nx + CELL * CELL + nz * nz));
    int level = AMBIENT + ((DIFFUSE * (int)udiv_lane((unsigned int)dot, len, 26)) >> 14);
    unsigned int c = SAND;

    c = (unsigned int)select_mask(mask_of(hs > SAND_TOP), GRASS, (int)c);
    c = (unsigned int)select_mask(mask_of(hs > GRASS_TOP), FOREST, (int)c);
    c = (unsigned int)select_mask(mask_of(hs > FOREST_TOP), ROCK, (int)c);
    c = (unsigned int)select_mask(mask_of(hs > ROCK_TOP), SNOW, (int)c);
    c = scale_rgb(c, level + (int)(var & 15u) - 8);

    /* Water is flat at sea level: its color comes from the depth below. */
    unsigned int w = mix_rgb(SHALLOW, DEEP, min_int(max0(SEA - raw) >> 1, 256));

    c = (unsigned int)select_mask(mask_of(hs <= 3 * SEA), (int)scale_rgb(w, 236 + (int)(var & 15u)), (int)c);
    return mix_rgb(c, HORIZON, min_int((max0(zc - FOG_NEAR) * FOG_SCALE) >> 8, 256));
}

/* SHADE of every cell: T1's color and visible bit in the high half, T2's in
 * the low half. A triangle's corners are v00, v11 and v01 (T1) or v10 (T2). */
INLINE void cell_shading(void)
{
    /* The row loop's state lives in DMEM: the shading needs every register. */
    VIEW[V_ROW] = 0;
    VIEW[V_DONE] = 0;
    for (;;) {
        int i = VIEW[V_ROW];

        if (i >= ROWS)
            break;

        int half = HALF(i);
        int s = LANE() & -(LANE() < 2 * half);
        int gx = VIEW[V_GX0] + cell_column(s, half), gz = VIEW[V_GZ0] + i;
        unsigned int bounds = (unsigned int)BOUNDS[CELLS - VIEW[V_DONE] - 2 * half + s];
        unsigned int var = hash2(gx, gz);
        unsigned int shade = 0;

        /* The trip counts are hidden from the compiler, which would
         * otherwise copy the loop bodies (and run out of IMEM). */
        int two = opaque(2), three = opaque(3);

        for (int t = 0; t < two; t++) {
            int ha = 0, hb = 0, hc = 0, raw = 1 << 20;

            for (int k = 0; k < three; k++) {
                /* corner k: (0, 0), (1, 1), then (1 - t, t) */
                int r = terrain_height(gx + (k != 0) - (k == 2) * t, gz + (k == 1) + (k == 2) * t);

                raw = min_int(raw, r);
                ha = hb;
                hb = hc;
                hc = max_int(r, SEA);
            }

            /* Normal (nx, 1, nz) with u = h(v00) - h(C), v = h(C) - h(v11):
             * T1 has (u, v), T2 (v, u). */
            int u = ha - hc, v = hc - hb;
            int nx = t ? v : u, nz = t ? u : v;
            int dy = ((ha + hb) >> 1) - VIEW[V_CY];
            int dz = gz * CELL + CELL / 2 - VIEW[V_CZ];
            int zc = (dz * VIEW[V_CPITCH] - dy * VIEW[V_SPITCH]) >> 14;
            unsigned int c = triangle_color(nx, nz, ha + hb + hc, raw, zc, var);

            shade = (shade << 16) | to_rgb555(c) | (((bounds >> (B_VIS1 + t)) & 1u) << 15);
            var >>= 8;
        }
        half = HALF(VIEW[V_ROW]);
        store_if(LANE() < 2 * half, &SHADE[CELLS - VIEW[V_DONE] - 2 * half + (LANE() & -(LANE() < 2 * half))],
                 (int)shade);
        VIEW[V_DONE] = VIEW[V_DONE] + 2 * half;
        VIEW[V_ROW] = VIEW[V_ROW] + 1;
    }
}

/* For each cell row (in drawing order), the bands its cells reach:
 * first | last << 8, or first > last when none. */
INLINE void row_bands(void)
{
    int cell = 0;

#pragma GCC unroll 1
    for (int r = 0; r < ROWS; r++) {
        int n = 2 * HALF(ROWS - 1 - r);
        int lo = 255, hi = 0;

#pragma GCC unroll 1
        for (int s = 0; s < n; s++) {
            int w = BOUNDS[cell + s];

            if (w < 0) { /* valid; the same in every lane */
                lo = min_int(lo, w & 127);
                hi = max_int(hi, (w >> B_LAST) & 127);
            }
        }
        ROWBAND[r] = lo | (hi << 8);
        cell += n;
    }
}

/* ---- 3. Bands --------------------------------------------------------- */

/*
 * The band's cells, in drawing order, into CAND (chunks of 31), and for
 * each tile column a bit per cell that reaches it: MASK[4 * tile + chunk],
 * ended by a word with bit 31 set. Lane tid keeps the bits of tiles tid and
 * tid + 32.
 */
INLINE void gather(int band)
{
    int tiles = VIEW[V_TILES];
    int pos = 0, chunk = 0, cell = 0, vtop = VERTS;
    unsigned int m0 = 0, m1 = 0;

#pragma GCC unroll 1
    for (int r = 0; r < ROWS; r++) {
        int i = ROWS - 1 - r;
        int half = HALF(i), half1 = HALF(i + 1);
        int vrow1 = vtop - (2 * half1 + 1);
        int vrow = vrow1 - (2 * half + 1);
        int rb = ROWBAND[r];

        if (band >= (rb & 0xFF) && band <= (rb >> 8)) {
#pragma GCC unroll 1
            for (int s = 0; s < 2 * half; s++) {
                int w = BOUNDS[cell + s];

                if (w >= 0 || band < (w & 127) || band > ((w >> B_LAST) & 127) || chunk == MAX_CHUNKS)
                    continue;

                int j = s < half ? s - half : 2 * half - 1 - s;
                int entry = (vrow + j + half) | ((vrow1 + j + half1) << 10) | ((cell + s) << 20);
                int t0 = (w >> B_T0) & 63;
                unsigned int span = (unsigned int)(((w >> B_T1) & 63) - t0);

                store_uniform(&CAND[32 * chunk + pos], entry);
                m0 |= (unsigned int)((unsigned int)(LANE() - t0) <= span) << pos;
                m1 |= (unsigned int)((unsigned int)(LANE() + CORES - t0) <= span) << pos;
                if (++pos == 31) {
                    store_if(LANE() < tiles, &MASK[4 * LANE() + chunk], (int)m0);
                    store_if(LANE() + CORES < tiles, &MASK[4 * (LANE() + CORES) + chunk], (int)m1);
                    chunk++;
                    pos = 0;
                    m0 = m1 = 0;
                }
            }
        }
        cell += 2 * half;
        vtop = vrow1;
    }
    if (pos != 0) {
        store_if(LANE() < tiles, &MASK[4 * LANE() + chunk], (int)m0);
        store_if(LANE() + CORES < tiles, &MASK[4 * (LANE() + CORES) + chunk], (int)m1);
        chunk++;
    }
    store_if(LANE() < tiles, &MASK[4 * LANE() + chunk], LIST_END);
    store_if(LANE() + CORES < tiles, &MASK[4 * (LANE() + CORES) + chunk], LIST_END);
    store_uniform(&MASK[4 * tiles], BAND_END);
}

#ifdef __riscv
#define FB_ROW() ((volatile unsigned int *)(uintptr_t)LANEROW[LANE()])
#define FB_WIDTH    GPGPU_ARGS[1]
#else
static unsigned int *native_fb; /* the band's first row */
static int native_width;
#define FB_ROW() (native_fb + LANE())
#define FB_WIDTH    native_width
#endif

/*
 * Painting a tile. A lane keeps its 8 pixels of the tile (column
 * x = 32 * tile + tid, the band's 8 rows) in registers. Bit k of the tile's
 * MASK word for chunk c is cell CAND[32 * c + k]; each cell, in drawing
 * order, paints the pixels its triangles cover:
 *
 *   T1 = v00 v11 v01 and T2 = v00 v10 v11 share the diagonal v00-v11. An
 *   edge a -> b has A = ay - by, B = bx - ax and the function
 *   A (x - ax) + B (y - ay), >= 0 on the inside; at the lane's pixel,
 *   (dx, dy) from v00, that is A dx + B dy + (its value at v00), and it
 *   changes by 4 B per row (Q2). A pixel exactly on an edge belongs to the
 *   triangle only on a left or top edge (the top-left rule: A > 0, or A == 0
 *   and B > 0; otherwise the function is lowered by 1), so neighbouring
 *   triangles never paint a pixel twice or leave one out. T2's diagonal is
 *   T1's reversed, so its function there is ~d, rule included.
 *
 *   A pixel takes T1's color where T1's three functions are >= 0, T2's where
 *   T2's are: with out = (e1 | e2 | e3) >> 31 (all ones when outside),
 *   p = ((p ^ c) & out) ^ c.
 *
 * This C is the reference (the native build runs it); the GPU runs the same
 * steps written in assembly (TILE_ASM below).
 */
#define EDGE_AT(e, step, A, B, e0)                                         \
    do {                                                                   \
        int ea_ = (A), eb_ = (B);                                          \
        e = ea_ * dx + eb_ * dy + (e0) + (((ea_ << 16) + eb_) >> 31);      \
        step = eb_ << 2;                                                   \
    } while (0)

#define PAINT_ROW(p)                                                       \
    do {                                                                   \
        unsigned int t_ = (unsigned int)((d | a1 | a2) >> 31);             \
        p = ((p ^ col1) & t_) ^ col1;                                      \
        t_ = (unsigned int)((~d | b1 | b2) >> 31);                         \
        p = ((p ^ col2) & t_) ^ col2;                                      \
        d += ds; a1 += a1s; a2 += a2s; b1 += b1s; b2 += b2s;               \
    } while (0)

/* Packed vertex coordinates. */
#define VX(v) ((int)((v) >> 16))
#define VY(v) ((int)(((v) << 16) >> 16))

#ifndef __riscv

/* The cells of the chunk whose MASK word is at pm, painted into p[8]. */
static void paint_chunk(volatile int *pm, unsigned int *p)
{
    unsigned int m = (unsigned int)*pm;

    while (m != 0) {
        int k = 0;

        while (!((m >> k) & 1u))
            k++;
        m &= m - 1;

        int entry = CAND[32 * ((pm - MASK) & 3) + k];
        int a = entry & 1023, b = (entry >> 10) & 1023;
        unsigned int v00 = (unsigned int)VERT[a], v01 = (unsigned int)VERT[a + 1];
        unsigned int v10 = (unsigned int)VERT[b], v11 = (unsigned int)VERT[b + 1];
        int x00 = VX(v00), y00 = VY(v00);
        int dx = 32 * (int)((pm - MASK) & ~3) + 4 * LANE() + 2 + GUARD - x00;
        int dy = VIEW[V_PY] - y00;
        int u01 = VX(v01) - x00, w01 = VY(v01) - y00;
        int u10 = VX(v10) - x00, w10 = VY(v10) - y00;
        int u11 = VX(v11) - x00, w11 = VY(v11) - y00;
        int d, ds, a1, a1s, a2, a2s, b1, b1s, b2, b2s;

        EDGE_AT(d, ds, -w11, u11, 0);                   /* v00 -> v11 */
        EDGE_AT(a1, a1s, w11 - w01, u01 - u11,          /* v11 -> v01 */
                (w01 - w11) * u11 + (u11 - u01) * w11);
        EDGE_AT(a2, a2s, w01, -u01, 0);                 /* v01 -> v00 */
        EDGE_AT(b1, b1s, -w10, u10, 0);                 /* v00 -> v10 */
        EDGE_AT(b2, b2s, w10 - w11, u11 - u10,          /* v10 -> v11 */
                (w11 - w10) * u10 + (u10 - u11) * w10);

        unsigned int shade = (unsigned int)SHADE[entry >> 20];
        unsigned int col1 = from_rgb555(shade >> 16), col2 = from_rgb555(shade);

        if (!(shade & 0x80000000u)) { /* T1 faces away: never inside */
            a1 = -1;
            a1s = 0;
        }
        if (!(shade & 0x8000u)) {
            b1 = -1;
            b1s = 0;
        }
        for (int row = 0; row < TILE_H; row++)
            PAINT_ROW(p[row]);
    }
}

#else

/*
 * The tile loop in assembly, the GPU's hot loop: in C the compiler kept some
 * of the 8 pixels on the stack, and a load or store there takes as long as
 * 20 instructions. GCC holds the pixels and pm | py << 16 (pm: the tile's
 * current MASK word, py: the band's first pixel row) in 9 registers; the
 * asm has the other 18 to itself:
 *
 *   t0  mask bits left           t1  entry, then 4 * cell, then SHADE word
 *   t2  dx, then T1's color      a0  dy, then T2's color
 *   a1..a6  corners relative to v00: u10 w10 u11 w11 u01 w01
 *   a7  d (edge v00 -> v11)      t3  its step
 *   s10 a1 (edge v11 -> v01)     s9  its step
 *   a4  b1 (edge v00 -> v10)     s11 its step
 *   t4  S1 = d + a1 + a2         a5  S2 = b1 + b2 - d
 *   t5, ra  scratch
 *
 * A triangle's three edge functions sum to a constant (twice its area), so
 * the third edge of each is derived in every row, not stepped:
 * a2 = S1 - d - a1 and b2 = S2 + d - b1. The edges a1 and b2 are evaluated
 * from their own first corner (v11, v10), so each takes two products. MUL
 * results come a few cycles late: independent work sits between a MUL and
 * the first use of its result.
 *
 * It paints chunk after chunk until the tile's list ends (a negative MASK
 * word: 0x80000000), leaving pm there; at the end of the band (0xC0000000)
 * it sets bit 0 of pmp instead.
 */
#define PAINT_ROW_ASM(p)                                                   \
    "sub  ra, t4, a7\n\t"          /* a2 = S1 - d - a1 */                  \
    "sub  ra, ra, s10\n\t"                                                 \
    "or   ra, ra, a7\n\t"                                                  \
    "or   ra, ra, s10\n\t"                                                 \
    "srai ra, ra, 31\n\t"          /* all ones: outside T1 */              \
    "xor  %[" p "], %[" p "], t2\n\t"                                      \
    "and  %[" p "], %[" p "], ra\n\t"                                      \
    "xor  %[" p "], %[" p "], t2\n\t"                                      \
    "add  ra, a5, a7\n\t"          /* b2 = S2 + d - b1 */                  \
    "sub  ra, ra, a4\n\t"                                                  \
    "or   ra, ra, a4\n\t"                                                  \
    "not  t5, a7\n\t"              /* ~d: T2's diagonal */                 \
    "or   ra, ra, t5\n\t"                                                  \
    "srai ra, ra, 31\n\t"          /* all ones: outside T2 */              \
    "xor  %[" p "], %[" p "], a0\n\t"                                      \
    "and  %[" p "], %[" p "], ra\n\t"                                      \
    "xor  %[" p "], %[" p "], a0\n\t"                                      \
    "add  a7, a7, t3\n\t"          /* next row */                          \
    "add  s10, s10, s9\n\t"                                                \
    "add  a4, a4, s11\n\t"

#define TILE_ASM                                                           \
    "10:\n\t"                      /* next chunk */                        \
    "slli t1, %[pmp], 16\n\t"                                              \
    "srli t1, t1, 16\n\t"                                                  \
    "lw   t0, 0(t1)\n\t"                                                   \
    "bltz t0, 19f\n\t"                                                     \
    "beqz t0, 18f\n"                                                       \
    "11:\n\t"                      /* next cell: k = lowest set bit */     \
    "neg  ra, t0\n\t"                                                      \
    "and  ra, ra, t0\n\t"                                                  \
    "li   a7, 0\n\t"                                                       \
    "slli t3, ra, 16\n\t"                                                  \
    "bnez t3, 1f\n\t"                                                      \
    "addi a7, a7, 16\n\t"                                                  \
    "srli ra, ra, 16\n"                                                    \
    "1:\n\t"                                                               \
    "slli t3, ra, 24\n\t"                                                  \
    "bnez t3, 1f\n\t"                                                      \
    "addi a7, a7, 8\n\t"                                                   \
    "srli ra, ra, 8\n"                                                     \
    "1:\n\t"                                                               \
    "slli t3, ra, 28\n\t"                                                  \
    "bnez t3, 1f\n\t"                                                      \
    "addi a7, a7, 4\n\t"                                                   \
    "srli ra, ra, 4\n"                                                     \
    "1:\n\t"                                                               \
    "slli t3, ra, 30\n\t"                                                  \
    "bnez t3, 1f\n\t"                                                      \
    "addi a7, a7, 2\n\t"                                                   \
    "srli ra, ra, 2\n"                                                     \
    "1:\n\t"                                                               \
    "slli t3, ra, 31\n\t"                                                  \
    "bnez t3, 1f\n\t"                                                      \
    "addi a7, a7, 1\n"                                                     \
    "1:\n\t"                                                               \
    "addi ra, t0, -1\n\t"                                                  \
    "and  t0, t0, ra\n\t"          /* cleared */                           \
    /* entry = CAND[32 * chunk + k], chunk = (pm >> 2) & 3 */              \
    "slli t1, %[pmp], 16\n\t"                                              \
    "srli t1, t1, 16\n\t"                                                  \
    "andi ra, t1, 12\n\t"                                                  \
    "slli ra, ra, 5\n\t"                                                   \
    "slli a7, a7, 2\n\t"                                                   \
    "add  ra, ra, a7\n\t"                                                  \
    "li   a7, %[cand]\n\t"                                                 \
    "add  ra, ra, a7\n\t"                                                  \
    "lw   t1, 0(ra)\n\t"                                                   \
    /* the corners: v00 v01 at a, v10 v11 at b */                          \
    "andi ra, t1, 1023\n\t"                                                \
    "slli ra, ra, 2\n\t"                                                   \
    "srli a7, t1, 10\n\t"                                                  \
    "andi a7, a7, 1023\n\t"                                                \
    "slli a7, a7, 2\n\t"                                                   \
    "srli t1, t1, 20\n\t"                                                  \
    "slli t1, t1, 2\n\t"           /* 4 * cell */                          \
    "lw   a5, %[vert]+4(ra)\n\t"   /* v01 */                               \
    "lw   ra, %[vert](ra)\n\t"     /* v00 */                               \
    "lw   a1, %[vert](a7)\n\t"     /* v10 */                               \
    "lw   a3, %[vert]+4(a7)\n\t"   /* v11 */                               \
    "srli t3, ra, 16\n\t"          /* x00 */                               \
    "slli ra, ra, 16\n\t"                                                  \
    "srli ra, ra, 16\n\t"          /* y00 */                               \
    /* dx = x - x00, x = 8 * (pm & ~15) + 4 * tid + kx; dy = py - y00 */   \
    "slli t2, %[pmp], 16\n\t"                                              \
    "srli t2, t2, 16\n\t"                                                  \
    "andi t2, t2, -16\n\t"                                                 \
    "slli t2, t2, 3\n\t"                                                   \
    "slli a7, x31, 2\n\t"                                                  \
    "add  t2, t2, a7\n\t"                                                  \
    "li   a7, %[kx]\n\t"                                                   \
    "add  t2, t2, a7\n\t"                                                  \
    "sub  t2, t2, t3\n\t"          /* dx */                                \
    "srli a0, %[pmp], 16\n\t"                                              \
    "sub  a0, a0, ra\n\t"          /* dy */                                \
    /* corners relative to v00 */                                          \
    "slli a2, a1, 16\n\t"                                                  \
    "srli a2, a2, 16\n\t"                                                  \
    "sub  a2, a2, ra\n\t"          /* w10 */                               \
    "srli a1, a1, 16\n\t"                                                  \
    "sub  a1, a1, t3\n\t"          /* u10 */                               \
    "slli a4, a3, 16\n\t"                                                  \
    "srli a4, a4, 16\n\t"                                                  \
    "sub  a4, a4, ra\n\t"          /* w11 */                               \
    "srli a3, a3, 16\n\t"                                                  \
    "sub  a3, a3, t3\n\t"          /* u11 */                               \
    "slli a6, a5, 16\n\t"                                                  \
    "srli a6, a6, 16\n\t"                                                  \
    "sub  a6, a6, ra\n\t"          /* w01 */                               \
    "srli a5, a5, 16\n\t"                                                  \
    "sub  a5, a5, t3\n\t"          /* u01 */                               \
    /* d = u11 dy - w11 dx and a2 = w01 dx - u01 dy, from v00 */           \
    "mul  a7, a4, t2\n\t"                                                  \
    "mul  t3, a3, a0\n\t"                                                  \
    "mul  t4, a6, t2\n\t"                                                  \
    "mul  t5, a5, a0\n\t"                                                  \
    "slli s9, a4, 16\n\t"          /* top-left rule: A << 16 + B < 0 */    \
    "sub  s9, a3, s9\n\t"          /* lowers the edge by 1 */              \
    "srai s9, s9, 31\n\t"                                                  \
    "slli s10, a6, 16\n\t"                                                 \
    "sub  s10, s10, a5\n\t"                                                \
    "srai s10, s10, 31\n\t"                                                \
    "sub  a7, t3, a7\n\t"                                                  \
    "add  a7, a7, s9\n\t"          /* d */                                 \
    "slli t3, a3, 2\n\t"           /* its step */                          \
    "sub  t4, t4, t5\n\t"                                                  \
    "add  t4, t4, s10\n\t"         /* a2 */                                \
    /* a1 = A (dx - u11) + B (dy - w11), A = w11 - w01, B = u01 - u11 */   \
    "sub  t5, a4, a6\n\t"                                                  \
    "sub  s9, a5, a3\n\t"                                                  \
    "sub  s10, t2, a3\n\t"                                                 \
    "sub  s11, a0, a4\n\t"                                                 \
    "mul  s10, t5, s10\n\t"                                                \
    "mul  s11, s9, s11\n\t"                                                \
    "slli t5, t5, 16\n\t"                                                  \
    "add  t5, t5, s9\n\t"                                                  \
    "srai t5, t5, 31\n\t"                                                  \
    "slli s9, s9, 2\n\t"           /* a1's step */                         \
    /* b2 = A (dx - u10) + B (dy - w10), A = w10 - w11, B = u11 - u10 */   \
    "sub  a5, a2, a4\n\t"                                                  \
    "sub  a6, a3, a1\n\t"                                                  \
    "add  s10, s10, s11\n\t"                                               \
    "add  s10, s10, t5\n\t"        /* a1 */                                \
    "add  t4, t4, a7\n\t"                                                  \
    "add  t4, t4, s10\n\t"         /* S1 */                                \
    "sub  a3, t2, a1\n\t"                                                  \
    "sub  a4, a0, a2\n\t"                                                  \
    "mul  a3, a5, a3\n\t"                                                  \
    "mul  a4, a6, a4\n\t"                                                  \
    /* b1 = u10 dy - w10 dx */                                             \
    "mul  t2, a2, t2\n\t"                                                  \
    "mul  a0, a1, a0\n\t"                                                  \
    "slli a5, a5, 16\n\t"                                                  \
    "add  a5, a5, a6\n\t"                                                  \
    "srai a5, a5, 31\n\t"                                                  \
    "slli ra, a2, 16\n\t"                                                  \
    "sub  ra, a1, ra\n\t"                                                  \
    "srai ra, ra, 31\n\t"                                                  \
    "slli s11, a1, 2\n\t"          /* b1's step */                         \
    "add  a3, a3, a4\n\t"                                                  \
    "add  a3, a3, a5\n\t"          /* b2 */                                \
    "sub  a4, a0, t2\n\t"                                                  \
    "add  a4, a4, ra\n\t"          /* b1 */                                \
    "add  a5, a3, a4\n\t"                                                  \
    "sub  a5, a5, a7\n\t"          /* S2 */                                \
    /* the colors and visible bits */                                      \
    "lw   t1, %[shade](t1)\n\t"                                            \
    "bltz t1, 1f\n\t"                                                      \
    "li   s10, -1\n\t"             /* T1 faces away: never inside */       \
    "li   s9, 0\n"                                                         \
    "1:\n\t"                                                               \
    "slli ra, t1, 16\n\t"                                                  \
    "bltz ra, 1f\n\t"                                                      \
    "li   a4, -1\n\t"                                                      \
    "li   s11, 0\n"                                                        \
    "1:\n\t"                                                               \
    "srli ra, t1, 26\n\t"          /* T1: RGB555 to 0x00RRGGBB in t2 */    \
    "andi ra, ra, 31\n\t"                                                  \
    "slli t2, ra, 19\n\t"                                                  \
    "srli ra, t1, 21\n\t"                                                  \
    "andi ra, ra, 31\n\t"                                                  \
    "slli ra, ra, 11\n\t"                                                  \
    "or   t2, t2, ra\n\t"                                                  \
    "srli ra, t1, 16\n\t"                                                  \
    "andi ra, ra, 31\n\t"                                                  \
    "slli ra, ra, 3\n\t"                                                   \
    "or   t2, t2, ra\n\t"                                                  \
    "srli ra, t1, 10\n\t"          /* T2 in a0 */                          \
    "andi ra, ra, 31\n\t"                                                  \
    "slli a0, ra, 19\n\t"                                                  \
    "srli ra, t1, 5\n\t"                                                   \
    "andi ra, ra, 31\n\t"                                                  \
    "slli ra, ra, 11\n\t"                                                  \
    "or   a0, a0, ra\n\t"                                                  \
    "andi ra, t1, 31\n\t"                                                  \
    "slli ra, ra, 3\n\t"                                                   \
    "or   a0, a0, ra\n\t"                                                  \
    PAINT_ROW_ASM("p0") PAINT_ROW_ASM("p1") PAINT_ROW_ASM("p2")            \
    PAINT_ROW_ASM("p3") PAINT_ROW_ASM("p4") PAINT_ROW_ASM("p5")            \
    PAINT_ROW_ASM("p6") PAINT_ROW_ASM("p7")                                \
    "bnez t0, 11b\n"                                                       \
    "18:\n\t"                                                              \
    "addi %[pmp], %[pmp], 4\n\t"                                           \
    "j    10b\n"                                                           \
    "19:\n\t"                      /* end of the list or of the band */    \
    "slli t0, t0, 1\n\t"                                                   \
    "bgez t0, 1f\n\t"                                                      \
    "ori  %[pmp], %[pmp], 1\n"                                             \
    "1:\n\t"

#endif

INLINE unsigned int sky_color(int band)
{
    return SKY_TOP + (unsigned int)min_int(band, SKY_STEPS) * SKY_STEP;
}

/*
 * The band's tiles, left to right: each lane paints its 8 pixels of a tile
 * with the tile's cells, then stores them, one row of the tile per store.
 * The band's first pixel row and sky come from VIEW[V_PY].
 */
INLINE void draw_band(void)
{
#ifdef __riscv
    /* pm and py share one register, so the asm gets the others. */
    unsigned int pmp = (unsigned int)(4 * W_MASK) | ((unsigned int)VIEW[V_PY] << 16);

    for (;;) {
        unsigned int sky = sky_color((int)(((pmp >> 16) - 2 - GUARD) >> 5));
        unsigned int p0 = sky, p1 = sky, p2 = sky, p3 = sky, p4 = sky, p5 = sky, p6 = sky, p7 = sky;

        __asm__ volatile(TILE_ASM
                         : [pmp] "+r"(pmp), [p0] "+r"(p0), [p1] "+r"(p1), [p2] "+r"(p2),
                           [p3] "+r"(p3), [p4] "+r"(p4), [p5] "+r"(p5), [p6] "+r"(p6), [p7] "+r"(p7)
                         : [cand] "i"(4 * W_CAND), [vert] "i"(4 * W_VERT),
                           [shade] "i"(4 * W_SHADE), [kx] "i"(2 + GUARD - 32 * W_MASK)
                         : "t0", "t1", "t2", "t3", "t4", "t5", "a0", "a1", "a2", "a3", "a4",
                           "a5", "a6", "a7", "s9", "s10", "s11", "ra", "memory");
        if (pmp & 1u)
            break;
        pmp &= ~15u;

        /* Tile (pm - MASK) / 16 bytes: its pixels are 32 * that words in. */
        volatile unsigned int *p = FB_ROW() + 2 * ((pmp & 0xFFFFu) - 4 * W_MASK);
        int w = FB_WIDTH;

        p[0] = p0;
        p += w;
        p[0] = p1;
        p += w;
        p[0] = p2;
        p += w;
        p[0] = p3;
        p += w;
        p[0] = p4;
        p += w;
        p[0] = p5;
        p += w;
        p[0] = p6;
        p += w;
        p[0] = p7;
        pmp += 16;
    }
#else
    int band = (VIEW[V_PY] - 2 - GUARD) >> 5;

    for (volatile int *pt = MASK; *pt != BAND_END; pt += 4) {
        unsigned int px[TILE_H];

        for (int row = 0; row < TILE_H; row++)
            px[row] = sky_color(band);
        for (volatile int *pm = pt; *pm >= 0; pm++)
            paint_chunk(pm, px);
        for (int row = 0; row < TILE_H; row++)
            FB_ROW()[8 * (pt - MASK) + row * FB_WIDTH] = px[row];
    }
#endif
}

#ifdef __riscv

void main(void)
{
    view_setup(GPGPU_ARGS[1], GPGPU_ARGS[2], GPGPU_ARGS[3]);
    vertex_pass();
    cell_geometry();
    cell_shading();
    row_bands();

    /* The band loop's state lives in DMEM, so that the tile loop has every
     * register it can get. */
    store_uniform(&VIEW[V_BAND], 0);
    for (;;) {
        int band = VIEW[V_BAND];

        if (band >= VIEW[V_BANDS])
            break;
        gather(band);
        LANEROW[LANE()] = GPGPU_ARGS[0] + 4 * (band * TILE_H * GPGPU_ARGS[1] + LANE());
        store_uniform(&VIEW[V_PY], band * (4 * TILE_H) + 2 + GUARD);
        draw_band();
        store_uniform(&VIEW[V_BAND], VIEW[V_BAND] + 1);
    }

    /* Every lane stores the same value. */
    GPGPU_ARGS[3] = GPGPU_ARGS[3] + 1;

    return;
}

GPGPU_START(main)

#else

#include <stdio.h>
#include <stdlib.h>

/* ./terrain_x86 width height frame > terrain.ppm draws that frame, running
 * each lane's code in turn, phase by phase, as the GPU runs them together. */
int main(int argc, char **argv)
{
    if (argc != 4) {
        fprintf(stderr, "usage: %s width height frame\n", argv[0]);
        return 1;
    }

    int width = (int)strtol(argv[1], NULL, 0);
    int height = (int)strtol(argv[2], NULL, 0);
    int frame = (int)strtol(argv[3], NULL, 0);

    if (width < CORES || width % CORES != 0 || width > CORES * MAX_TILES || height < TILE_H ||
        height % TILE_H != 0) {
        fprintf(stderr, "width must be a multiple of %d up to %d, height a multiple of %d\n",
                CORES, CORES * MAX_TILES, TILE_H);
        return 1;
    }

    unsigned int *fb = calloc((size_t)width * (size_t)height, sizeof *fb);
    if (fb == NULL)
        return 1;
    native_width = width;
    for (native_lane = 0; native_lane < CORES; native_lane++)
        view_setup(width, height, frame);
    for (native_lane = 0; native_lane < CORES; native_lane++)
        vertex_pass();
    for (native_lane = 0; native_lane < CORES; native_lane++)
        cell_geometry();
    for (native_lane = 0; native_lane < CORES; native_lane++)
        cell_shading();
    for (native_lane = 0; native_lane < CORES; native_lane++)
        row_bands();

    for (int band = 0; band < VIEW[V_BANDS]; band++) {
        for (native_lane = 0; native_lane < CORES; native_lane++) {
            gather(band);
            store_uniform(&VIEW[V_PY], band * (4 * TILE_H) + 2 + GUARD);
        }
        native_fb = fb + band * TILE_H * width;
        for (native_lane = 0; native_lane < CORES; native_lane++)
            draw_band();
    }

    printf("P6\n%d %d\n255\n", width, height);
    for (int i = 0; i < width * height; i++) {
        putchar((fb[i] >> 16) & 0xFF);
        putchar((fb[i] >> 8) & 0xFF);
        putchar(fb[i] & 0xFF);
    }
    free(fb);
    return 0;
}

#endif
