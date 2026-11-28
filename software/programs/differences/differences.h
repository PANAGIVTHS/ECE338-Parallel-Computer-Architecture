#ifndef DIFFERENCES_H
#define DIFFERENCES_H

/* What the kernel (differences.c) and the host program (host.c) share. */

#include "gpgpu_types.h"

/* The most differences one launch computes: the size of the device arrays. */
#define DIFFERENCES_MAX 4096

#endif /* DIFFERENCES_H */
