/*
 * nbody-3d: `steps` steps of 32 bodies in 3D, one body per lane.
 *
 * The state is in GMEM, which the host writes and reads (host.c): pos and
 * vel hold x for every body, then y, then z (3 * NBODIES words each), and
 * mass one word per body. Launch over gpgpu_dim3(1): the block copies the
 * positions and masses into shared memory, where every lane reads all of
 * them each step, and writes the state back at the end. The velocities wait
 * in shared memory too, each lane's in its own word.
 */
#include "gpgpu_device.h"
#include "nbody-3d.h"

/* Moving loop invariants (the shared-memory addresses of the lane's words)
 * out of the step loop keeps more values live than the registers hold, and
 * the spills overflow the lane's 128 bytes of stack. */
#pragma GCC optimize("no-move-loop-invariants", "no-tree-loop-im", "no-schedule-insns", "no-tree-pre", "no-gcse")

GPGPU_DEVICE int state_pos[3 * NBODIES];
GPGPU_DEVICE int state_vel[3 * NBODIES];
GPGPU_DEVICE int state_mass[NBODIES];

GPGPU_SHARED volatile int pos_x[NBODIES];
GPGPU_SHARED volatile int pos_y[NBODIES];
GPGPU_SHARED volatile int pos_z[NBODIES];
GPGPU_SHARED volatile int masses[NBODIES];
/* Each lane's own velocity: kept here, not in registers, so the step loop
 * fits the lane's 128 bytes of stack. */
GPGPU_SHARED volatile int vel_x[NBODIES];
GPGPU_SHARED volatile int vel_y[NBODIES];
GPGPU_SHARED volatile int vel_z[NBODIES];

GPGPU_GLOBAL void nbody_3d(int *pos, int *vel, const int *mass, int steps)
{
    unsigned int i = gpgpu_thread_idx();
    int xi = pos[i], yi = pos[NBODIES + i], zi = pos[2 * NBODIES + i];

    vel_x[i] = vel[i];
    vel_y[i] = vel[NBODIES + i];
    vel_z[i] = vel[2 * NBODIES + i];
    masses[i] = mass[i];
    for (int step = 0; step < steps; step++) {
        int a[3];

        pos_x[i] = xi;
        pos_y[i] = yi;
        pos_z[i] = zi;
        gpgpu_syncthreads();
        nbody_3d_accel(xi, yi, zi, pos_x, pos_y, pos_z, masses, a);
        gpgpu_syncthreads(); /* every lane has read the positions of this step */
        vel_x[i] = vel_x[i] + quarter(a[0]);
        vel_y[i] = vel_y[i] + quarter(a[1]);
        vel_z[i] = vel_z[i] + quarter(a[2]);
        xi += vel_x[i];
        yi += vel_y[i];
        zi += vel_z[i];
    }
    pos[i] = xi;
    pos[NBODIES + i] = yi;
    pos[2 * NBODIES + i] = zi;
    vel[i] = vel_x[i];
    vel[NBODIES + i] = vel_y[i];
    vel[2 * NBODIES + i] = vel_z[i];
}
