/*
 * terrain: one frame of the flight over the landscape of terrain.h.
 *
 * One block draws the frame: launch it over gpgpu_dim3(1). The phases and
 * their state in shared memory are in terrain.h.
 */
#include "terrain.h"

GPGPU_GLOBAL void terrain(unsigned int *fb, int width, int height, int frame)
{
    /* The parameters go to shared memory: the tile loop wants every register. */
    store_uniform(&VIEW[V_FB], (int)(uintptr_t)fb);
    store_uniform(&VIEW[V_WIDTH], width);
    store_uniform(&VIEW[V_HEIGHT], height);
    store_uniform(&VIEW[V_FRAME], frame);
    view_setup(VIEW[V_WIDTH], VIEW[V_HEIGHT], VIEW[V_FRAME]);
    vertex_pass();
    cell_geometry();
    cell_shading();
    row_bands();

    /* The band loop's state lives in SMEM, so that the tile loop has every
     * register it can get. */
    store_uniform(&VIEW[V_BAND], 0);
    for (;;) {
        int band = VIEW[V_BAND];

        if (band >= VIEW[V_BANDS])
            break;
        gather(band);
        LANEROW[LANE()] = VIEW[V_FB] + 4 * (band * TILE_H * VIEW[V_WIDTH] + LANE());
        store_uniform(&VIEW[V_PY], band * (4 * TILE_H) + 2 + GUARD);
        draw_band();
        store_uniform(&VIEW[V_BAND], VIEW[V_BAND] + 1);
    }
}
