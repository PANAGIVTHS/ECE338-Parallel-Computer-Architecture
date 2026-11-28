#ifndef MEMSPACES_H
#define MEMSPACES_H

/* What the kernels (memspaces.c) and the host program (host.c) share. */

#include "gpgpu_types.h"

#define MEMSPACES_LANES   GPGPU_BLOCK_SIZE
#define MEMSPACES_BLOCKS  2u
#define MEMSPACES_THREADS (MEMSPACES_BLOCKS * MEMSPACES_LANES)

_Static_assert((MEMSPACES_LANES & (MEMSPACES_LANES - 1u)) == 0, "a neighbour index is a mask: the lanes are a power of two");

/* The initial values of the kernels' globals. */
#define MEMSPACES_GAIN        { 3, 1, 4, 1, 5, 9, 2, 6 }
#define MEMSPACES_BIAS        { 1000, 2000, 3000, 4000 }
#define MEMSPACES_CALL_COUNT  100
#define MEMSPACES_OFFSETS     { 0, 10000 }

/* The switch of the kernel: 6 dense cases, so with jump tables GCC reads the
 * target from a table in .rodata. op is the same in every lane. */
static inline int memspaces_op(int op, int tid)
{
    switch (op) {
    case 0: return tid;
    case 1: return tid * 3;
    case 2: return tid + 77;
    case 3: return -tid;
    case 4: return tid << 4;
    case 5: return tid ^ 0x55;
    default: return 0;
    }
}

#endif /* MEMSPACES_H */
