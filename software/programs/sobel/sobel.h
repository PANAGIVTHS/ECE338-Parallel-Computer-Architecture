#ifndef SOBEL_H
#define SOBEL_H

/* What the kernel (sobel.c) and the host program (host.c) share: the size of
 * the image. */

#include "gpgpu_types.h"

#define SOBEL_WIDTH  16
#define SOBEL_HEIGHT 16
#define SOBEL_PIXELS (SOBEL_WIDTH * SOBEL_HEIGHT)

_Static_assert((SOBEL_WIDTH & (SOBEL_WIDTH - 1)) == 0, "x and y come from a mask and a shift, not a division");
_Static_assert(SOBEL_PIXELS % GPGPU_BLOCK_SIZE == 0, "every lane of every block has a pixel");

#endif /* SOBEL_H */
