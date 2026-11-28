/*
 * memspaces: kernels that touch every memory space of the runtime
 * (docs/runtime-spec.md, section 3). host.c launches them and checks the
 * results.
 *
 *   parameters  launch block, GMEM   op, results          every launch
 *   .rodata     GMEM                 gain[], jump table   private constants
 *   GPGPU_CONSTANT                   offsets[]            constants the host may rewrite
 *   .data       GMEM                 bias[]               private, initialized
 *   GPGPU_DEVICE                     call_count           exported, initialized
 *   .bss        GMEM                 last_op              private, zero
 *   GPGPU_DEVICE                     slots[], out[]       exported, zero
 *   GPGPU_SHARED  shared memory      neighbours[]         one block, undefined at its start
 *   stack       shared memory        tmp[]                one lane
 *
 * memspaces runs on a grid of MEMSPACES_BLOCKS blocks. Block b, lane t writes
 *
 *   out[b * LANES + t] = memspaces_op(op, t) + gain[t & 7] + bias[t & 3]
 *                        + call_count + slots[t] + (4 t + 6)
 *                        + (3 ((t + 1) & (LANES - 1)) + b) + offsets[b]
 *
 * to `results`, and the last block then sets slots[t] = t + 1 and adds 1 to
 * call_count: the globals keep their values from one launch to the next.
 *
 * memspaces_fault loads from a framebuffer, which kernels may only store to:
 * the launch faults with ST_PERMISSION in every lane.
 */
#include "gpgpu_device.h"
#include "memspaces.h"

static const int gain[8] = MEMSPACES_GAIN;
GPGPU_CONSTANT const int offsets[MEMSPACES_BLOCKS] = MEMSPACES_OFFSETS;

int bias[4] = MEMSPACES_BIAS;
GPGPU_DEVICE int call_count = MEMSPACES_CALL_COUNT;

int last_op;
GPGPU_DEVICE int slots[MEMSPACES_LANES];
GPGPU_DEVICE int out[MEMSPACES_THREADS];

GPGPU_SHARED int neighbours[MEMSPACES_LANES];

/* Jump tables are off for every kernel (-fno-jump-tables); this function asks
 * for them. It is not inlined: a kernel cannot have other optimize options. */
__attribute__((noinline, optimize("jump-tables"))) static int op_result(int op, int tid)
{
    return memspaces_op(op, tid);
}

GPGPU_GLOBAL void memspaces(int op, int *results)
{
    unsigned int tid = gpgpu_thread_idx();
    unsigned int block = gpgpu_block_idx_x();

    /* Stack: volatile keeps the array in this lane's stack. */
    volatile int tmp[4];
    for (int i = 0; i < 4; i++)
        tmp[i] = (int)tid + i;
    int tmp_sum = tmp[0] + tmp[1] + tmp[2] + tmp[3];

    /* Shared memory: written by every lane before any lane reads it. */
    neighbours[tid] = 3 * (int)tid + (int)block;
    gpgpu_syncthreads();
    int neighbour = neighbours[(tid + 1u) & (MEMSPACES_LANES - 1u)];

    results[block * MEMSPACES_LANES + tid] = op_result(op, (int)tid) + gain[tid & 7u] + bias[tid & 3u] + call_count +
                                             slots[tid] + tmp_sum + neighbour + offsets[block];

    /* Uniform: every lane is in the same block. All lanes store the same
     * call_count, so the lockstep lanes do not race. */
    if (block == gpgpu_grid_dim_x() - 1u) {
        slots[tid] = (int)tid + 1;
        last_op = op;
        call_count = call_count + 1;
    }
}

GPGPU_GLOBAL void memspaces_fault(const unsigned int *framebuffer, int *results)
{
    unsigned int tid = gpgpu_thread_idx();

    results[tid] = (int)framebuffer[tid];
}
