/*
 * nbody: `steps` steps of 32 bodies in 2D, one body per lane.
 *
 * The state is four arrays of NBODIES words in GMEM, which the host writes
 * and reads (host.c). Launch over gpgpu_dim3(1): the block copies the
 * positions into shared memory, where every lane reads all of them each
 * step, and writes the state back at the end.
 */
#include "gpgpu_device.h"
#include "nbody.h"

GPGPU_DEVICE int state_x[NBODIES], state_y[NBODIES], state_vx[NBODIES], state_vy[NBODIES];

GPGPU_SHARED volatile int pos_x[NBODIES];
GPGPU_SHARED volatile int pos_y[NBODIES];

GPGPU_GLOBAL void nbody(int *x, int *y, int *vx, int *vy, int steps)
{
    unsigned int i = gpgpu_thread_idx();
    int xi = x[i], yi = y[i], vxi = vx[i], vyi = vy[i];

    for (int step = 0; step < steps; step++) {
        int ax, ay;

        pos_x[i] = xi;
        pos_y[i] = yi;
        gpgpu_syncthreads();
        nbody_accel(xi, yi, pos_x, pos_y, &ax, &ay);
        gpgpu_syncthreads(); /* every lane has read the positions of this step */
        vxi += ax >> 2;
        vyi += ay >> 2;
        xi += vxi;
        yi += vyi;
    }
    x[i] = xi;
    y[i] = yi;
    vx[i] = vxi;
    vy[i] = vyi;
}
