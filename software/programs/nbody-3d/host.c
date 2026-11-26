/*
 * nbody-3d: the host program. Sets up 32 bodies, runs `steps` steps on the
 * GPU, `per_row` steps per launch, reading the positions back after each
 * launch, and checks them against the same steps computed here.
 *
 *   gpgpu_main([steps [per_row [csv]]])   default 100 steps, 1 per launch
 *
 * With a third argument "csv" it also prints the positions after each launch
 * as CSV (step,x0,y0,z0,...,x31,y31,z31).
 */
#include <stdlib.h>
#include <string.h>

#include "gpgpu.h"
#include "nbody-3d_kernels.h"

/* The kernel's layout: pos and vel are x for every body, then y, then z. */
typedef struct {
    int x[NBODIES], y[NBODIES], z[NBODIES];
} vec3s_t;

typedef struct {
    vec3s_t pos, vel;
    int mass[NBODIES];
} bodies_t;

/* One step of all the bodies, as the GPU's lanes take it together. */
static void reference_step(bodies_t *b)
{
    int a[NBODIES][3];

    for (unsigned int i = 0; i < NBODIES; i++)
        nbody_3d_accel(b->pos.x[i], b->pos.y[i], b->pos.z[i], b->pos.x, b->pos.y, b->pos.z, b->mass, a[i]);
    for (unsigned int i = 0; i < NBODIES; i++) {
        b->vel.x[i] += quarter(a[i][0]);
        b->vel.y[i] += quarter(a[i][1]);
        b->vel.z[i] += quarter(a[i][2]);
        b->pos.x[i] += b->vel.x[i];
        b->pos.y[i] += b->vel.y[i];
        b->pos.z[i] += b->vel.z[i];
    }
}

int gpgpu_main(int argc, char **argv)
{
    int steps = argc > 1 ? atoi(argv[1]) : 100;
    int per_row = argc > 2 ? atoi(argv[2]) : 1;
    int csv = argc > 3 && strcmp(argv[3], "csv") == 0;
    bodies_t want;
    vec3s_t got;
    unsigned int wrong = 0;

    if (steps < 1 || per_row < 1) {
        gpgpu_printf("steps and per_row must be at least 1\n");
        return 1;
    }
    for (unsigned int i = 0; i < NBODIES; i++) {
        want.pos.x[i] = init_x(i);
        want.pos.y[i] = init_y(i);
        want.pos.z[i] = init_z(i);
        want.vel.x[i] = init_vx(i);
        want.vel.y[i] = init_vy(i);
        want.vel.z[i] = init_vz(i);
        want.mass[i] = init_mass(i);
    }
    GPGPU_CHECK(gpgpu_memcpy_to_symbol(nbody_3d_sym_state_pos, &want.pos, sizeof want.pos, 0));
    GPGPU_CHECK(gpgpu_memcpy_to_symbol(nbody_3d_sym_state_vel, &want.vel, sizeof want.vel, 0));
    GPGPU_CHECK(gpgpu_memcpy_to_symbol(nbody_3d_sym_state_mass, want.mass, sizeof want.mass, 0));

    if (csv) {
        gpgpu_printf("step");
        for (unsigned int i = 0; i < NBODIES; i++)
            gpgpu_printf(",x%u,y%u,z%u", i, i, i);
        gpgpu_printf("\n");
    }
    uint32_t start = gpgpu_time_ms();
    for (int step = 0; step < steps;) {
        int n = steps - step < per_row ? steps - step : per_row;

        GPGPU_CHECK(gpgpu_launch(nbody_3d, gpgpu_dim3(1), gpgpu_symbol_address(nbody_3d_sym_state_pos),
                                 gpgpu_symbol_address(nbody_3d_sym_state_vel),
                                 gpgpu_symbol_address(nbody_3d_sym_state_mass), n));
        GPGPU_CHECK(gpgpu_memcpy_from_symbol(&got, nbody_3d_sym_state_pos, sizeof got, 0));
        for (int k = 0; k < n; k++)
            reference_step(&want);
        step += n;

        if (csv) {
            gpgpu_printf("%d", step);
            for (unsigned int i = 0; i < NBODIES; i++)
                gpgpu_printf(",%d,%d,%d", got.x[i], got.y[i], got.z[i]);
            gpgpu_printf("\n");
        }
        for (unsigned int i = 0; i < NBODIES; i++)
            if ((got.x[i] != want.pos.x[i] || got.y[i] != want.pos.y[i] || got.z[i] != want.pos.z[i]) && wrong++ < 4 &&
                !csv)
                gpgpu_printf("  step %d: body %u at (%d, %d, %d), expected (%d, %d, %d)\n", step, i, got.x[i],
                             got.y[i], got.z[i], want.pos.x[i], want.pos.y[i], want.pos.z[i]);
    }
    gpgpu_printf("nbody-3d: %d steps of %u bodies in %u ms\n", steps, NBODIES, (unsigned)(gpgpu_time_ms() - start));
    gpgpu_printf("%s: %u positions wrong\n", wrong ? "FAIL" : "PASS", wrong);
    return wrong ? 1 : 0;
}
