/*
 * memfault: every lane stores its index at target[lane]. The host aims it at
 * memory a kernel may not write, and checks the fault the runtime reports.
 */
#include "gpgpu_device.h"

GPGPU_DEVICE int out[GPGPU_NUM_CORES];

GPGPU_GLOBAL void memfault(volatile int *target)
{
    unsigned int tid = gpgpu_thread_idx();

    target[tid] = (int)tid;
}
