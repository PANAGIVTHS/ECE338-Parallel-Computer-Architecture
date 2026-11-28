#ifndef GPGPU_MODULE_H
#define GPGPU_MODULE_H

/* The module of a program: its kernels and their data, as the module builder
 * writes it (<p>_module.c). Internal to the runtime. */

#include "gpgpu.h"

typedef struct {
    const char *name;
    /* What the program was built for; checked against the hardware. */
    uint32_t abi_version;
    uint32_t num_cores;
    uint32_t imem_words;
    uint32_t shared_bytes;
    uint32_t gmem_base, gmem_size;
    uint32_t fb_base[2], fb_size;
    /* Its layout in GMEM (linker.ld). */
    uint32_t launch_block;
    uint32_t data_start, data_end; /* .rodata, .data, .bss */
    uint32_t bss_start, bss_end;
    /* Its images. */
    const uint32_t *imem;
    uint32_t imem_count;
    const uint32_t *gmem_image;
    uint32_t gmem_image_base, gmem_image_words;
} gpgpu_module_t;

extern const gpgpu_module_t gpgpu_module_;

#endif /* GPGPU_MODULE_H */
