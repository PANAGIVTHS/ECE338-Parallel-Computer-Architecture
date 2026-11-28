/*
 * nbody: the host program. Sets up 32 bodies, runs `steps` steps on the GPU,
 * `per_row` steps per launch, reading the positions back after each launch,
 * and checks them against the same steps computed here.
 *
 *   gpgpu_main([steps [per_row [csv]]])   default 100 steps, 1 per launch
 *
 * With a third argument "csv" it also prints the positions after each launch
 * as CSV (step,x0,y0,...,x31,y31), the input of visualize.py.
 */
#include <stdlib.h>
#include <string.h>

#include "gpgpu.h"
#include "nbody_kernels.h"

typedef struct {
    int x[NBODIES], y[NBODIES], vx[NBODIES], vy[NBODIES];
} bodies_t;

/* One step of all the bodies, as the GPU's lanes take it together. */
static void reference_step(bodies_t *b)
{
    int ax[NBODIES], ay[NBODIES];

    for (unsigned int i = 0; i < NBODIES; i++)
        nbody_accel(b->x[i], b->y[i], b->x, b->y, &ax[i], &ay[i]);
    for (unsigned int i = 0; i < NBODIES; i++) {
        b->vx[i] += ax[i] >> 2;
        b->vy[i] += ay[i] >> 2;
        b->x[i] += b->vx[i];
        b->y[i] += b->vy[i];
    }
}

int gpgpu_main(int argc, char **argv)
{
    int steps = argc > 1 ? atoi(argv[1]) : 100;
    int per_row = argc > 2 ? atoi(argv[2]) : 1;
    int csv = argc > 3 && strcmp(argv[3], "csv") == 0;
    bodies_t want, got;
    unsigned int wrong = 0;

    if (steps < 1 || per_row < 1) {
        gpgpu_printf("steps and per_row must be at least 1\n");
        return 1;
    }
    for (unsigned int i = 0; i < NBODIES; i++) {
        want.x[i] = init_x(i);
        want.y[i] = init_y(i);
        want.vx[i] = init_vx(i);
        want.vy[i] = init_vy(i);
    }
    GPGPU_CHECK(gpgpu_memcpy_to_symbol(nbody_sym_state_x, want.x, sizeof want.x, 0));
    GPGPU_CHECK(gpgpu_memcpy_to_symbol(nbody_sym_state_y, want.y, sizeof want.y, 0));
    GPGPU_CHECK(gpgpu_memcpy_to_symbol(nbody_sym_state_vx, want.vx, sizeof want.vx, 0));
    GPGPU_CHECK(gpgpu_memcpy_to_symbol(nbody_sym_state_vy, want.vy, sizeof want.vy, 0));

    if (csv) {
        gpgpu_printf("step");
        for (unsigned int i = 0; i < NBODIES; i++)
            gpgpu_printf(",x%u,y%u", i, i);
        gpgpu_printf("\n");
    }
    uint32_t start = gpgpu_time_ms();
    for (int step = 0; step < steps;) {
        int n = steps - step < per_row ? steps - step : per_row;

        GPGPU_CHECK(gpgpu_launch(nbody, gpgpu_dim3(1), gpgpu_symbol_address(nbody_sym_state_x),
                                 gpgpu_symbol_address(nbody_sym_state_y), gpgpu_symbol_address(nbody_sym_state_vx),
                                 gpgpu_symbol_address(nbody_sym_state_vy), n));
        GPGPU_CHECK(gpgpu_memcpy_from_symbol(got.x, nbody_sym_state_x, sizeof got.x, 0));
        GPGPU_CHECK(gpgpu_memcpy_from_symbol(got.y, nbody_sym_state_y, sizeof got.y, 0));
        for (int k = 0; k < n; k++)
            reference_step(&want);
        step += n;

        if (csv) {
            gpgpu_printf("%d", step);
            for (unsigned int i = 0; i < NBODIES; i++)
                gpgpu_printf(",%d,%d", got.x[i], got.y[i]);
            gpgpu_printf("\n");
        }
        for (unsigned int i = 0; i < NBODIES; i++)
            if ((got.x[i] != want.x[i] || got.y[i] != want.y[i]) && wrong++ < 4 && !csv)
                gpgpu_printf("  step %d: body %u at (%d, %d), expected (%d, %d)\n", step, i, got.x[i], got.y[i],
                             want.x[i], want.y[i]);
    }
    gpgpu_printf("nbody: %d steps of %u bodies in %u ms\n", steps, NBODIES, (unsigned)(gpgpu_time_ms() - start));
    gpgpu_printf("%s: %u positions wrong\n", wrong ? "FAIL" : "PASS", wrong);
    return wrong ? 1 : 0;
}
