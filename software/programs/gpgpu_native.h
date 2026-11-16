#ifndef GPGPU_NATIVE_H
#define GPGPU_NATIVE_H

/*
 * Native (x86) builds of kernels that take GPU byte addresses.
 *
 * Such a kernel reads 32-bit addresses from its descriptors and uses them as
 * pointers, as it does on the GPU. On a 64-bit host that only works for
 * memory below 4 GiB, so the native build takes its test memory from here.
 */

#ifndef __riscv

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/mman.h>

/* `bytes` of zeroed memory whose address fits 32 bits; exits when there is none. */
static inline void *gpgpu_native_alloc(size_t bytes)
{
    int flags = MAP_PRIVATE | MAP_ANONYMOUS;
    void *hint = NULL;

#ifdef MAP_32BIT
    flags |= MAP_32BIT;
#else
    hint = (void *)(uintptr_t)0x20000000u; /* a hint, checked below */
#endif
    void *memory = mmap(hint, bytes, PROT_READ | PROT_WRITE, flags, -1, 0);

    if (memory == MAP_FAILED || (uint64_t)(uintptr_t)memory + bytes > UINT64_C(0x100000000)) {
        fprintf(stderr, "gpgpu_native_alloc: no %zu bytes below 4 GiB\n", bytes);
        exit(1);
    }
    return memory;
}

static inline uint32_t gpgpu_native_address(const void *pointer)
{
    return (uint32_t)(uintptr_t)pointer;
}

#endif /* !__riscv */

#endif /* GPGPU_NATIVE_H */
