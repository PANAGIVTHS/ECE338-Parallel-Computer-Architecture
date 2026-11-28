/*
 * stress: the switching-activity test of stress.h on the GPU. The work of a
 * lane is stress_lane(); every lane writes its result to results[tid], so the
 * computation is not removed and the host can check it.
 *
 * Parameters:
 *   mode        MODE_*, optionally with a lane range (MODE_MASK)
 *   iterations  the loop count of the mode
 *   seed        0 keeps every data value at zero
 *   results     CORES words: each lane's result
 *   ddr         MODE_DDR's buffer, DDR_BURSTS * CORES words of a framebuffer
 *
 * MODE_SMEM works in this kernel's shared memory. The mode needs no jump
 * table: -fno-jump-tables is the default for every kernel (a table would be
 * .rodata in GMEM, a DDR load per dispatch).
 */
#include "gpgpu_device.h"
#include "stress.h"

GPGPU_SHARED unsigned int scratch[CORES];
GPGPU_DEVICE unsigned int results[CORES];

GPGPU_GLOBAL void stress(unsigned int mode, unsigned int iterations, unsigned int seed, unsigned int *results,
                         unsigned int *ddr)
{
    unsigned int tid = gpgpu_thread_idx();
    /* The same in every lane: a uniform choice. */
    volatile unsigned int *buf = (mode & MODE_MASK) == MODE_DDR ? (volatile unsigned int *)ddr : scratch;

    results[tid] = stress_lane(tid, mode, iterations, seed, buf);
}
