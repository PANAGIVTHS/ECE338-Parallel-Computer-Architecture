#ifndef GPGPU_TYPES_H
#define GPGPU_TYPES_H

/*
 * Types and constants that the host and the kernels share (docs/runtime-spec.md).
 * Both compilers see this file: the RISC-V one for kernels, the ARM or x86 one
 * for host programs. Only fixed-width types, so the layouts are the same.
 */

#include <stdint.h>

#include "gpgpu_config.h"

/* Version of the launch block layout (section 6.1), word 4 of every launch. */
#define GPGPU_ABI_VERSION 1u

/* Threads in a block: always the lanes of the SM. */
#define GPGPU_BLOCK_SIZE GPGPU_NUM_CORES

/* Each grid dimension is 1 to GPGPU_GRID_MAX: two block indices share a register. */
#define GPGPU_GRID_MAX 65535u

/* Byte address where shared memory starts in the BRAM (linker.ld). Address 0
 * is a valid shared variable, so kernels must not test shared pointers
 * against NULL. The host's reference of a kernel that addresses shared memory
 * directly (terrain) needs it too. */
#define GPGPU_SHARED_BASE 0

/* The launch block: GPGPU_LAUNCH_BYTES at GMEM_BASE, written by the host before
 * every launch and only read by the kernels. One 32-bit word per parameter. */
#define GPGPU_LAUNCH_BYTES  256u
#define GPGPU_LAUNCH_PARAMS 56u

typedef struct {
    uint32_t entry;       /* IMEM byte address of the kernel's entry function */
    uint32_t grid_x;
    uint32_t grid_y;
    uint32_t grid_z;
    uint32_t abi_version; /* GPGPU_ABI_VERSION */
    uint32_t reserved[3]; /* 0 */
    uint32_t params[GPGPU_LAUNCH_PARAMS];
} gpgpu_launch_block_t;

_Static_assert(sizeof(gpgpu_launch_block_t) == GPGPU_LAUNCH_BYTES, "the launch block is 256 bytes");

/* A grid of blocks, like CUDA's dim3. */
typedef struct {
    uint32_t x, y, z;
} gpgpu_dim3_t;

/* gpgpu_dim3(x), gpgpu_dim3(x, y) or gpgpu_dim3(x, y, z): a missing dimension
 * is 1. C has no default arguments, so the macro picks a form by the number of
 * arguments; four or more are a compile error. */
#define GPGPU_DIM3_1_(x)       ((gpgpu_dim3_t){ (x), 1u, 1u })
#define GPGPU_DIM3_2_(x, y)    ((gpgpu_dim3_t){ (x), (y), 1u })
#define GPGPU_DIM3_3_(x, y, z) ((gpgpu_dim3_t){ (x), (y), (z) })
#define GPGPU_DIM3_PICK_(a, b, c, macro, ...) macro
#define gpgpu_dim3(...) \
    GPGPU_DIM3_PICK_(__VA_ARGS__, GPGPU_DIM3_3_, GPGPU_DIM3_2_, GPGPU_DIM3_1_, 0)(__VA_ARGS__)

/* A kernel parameter's check, in the generated code of both sides: a pointer,
 * or an integer of at most 32 bits. */
#define GPGPU_PARAM_CHECK_(kernel, value, name)                                \
    _Static_assert(__builtin_classify_type(value) == 5 ||                      \
                   (__builtin_classify_type(value) == 1 && sizeof(value) <= 4), \
                   #kernel ": parameter '" name "' must be a pointer or an integer of at most 32 bits")

#endif /* GPGPU_TYPES_H */
