#ifndef SUBWORD_H
#define SUBWORD_H

/* What the kernel (subword.c) and the host program (host.c) share. */

#include <stddef.h>

#include "gpgpu_types.h"

/* Test 6 reads word tid and word tid + 31 of this many words in GMEM. */
#define SUBWORD_DDR_WORDS (GPGPU_NUM_CORES + 31u)

_Static_assert(GPGPU_NUM_CORES % 2 == 0, "test 5 pairs each lane with lane tid ^ 1");

#endif /* SUBWORD_H */
