#ifndef GPGPU_HOST_H
#define GPGPU_HOST_H

#include "xil_types.h"
#include "gpgpu_platform.h"

/* Physical AXI base: the Vitis flow defines it from
 * hardware.vivado.peripheral.base_address. */
#ifndef GPGPU_BASEADDR
#error "GPGPU_BASEADDR is not defined: build the host with the gpgpu Vitis flow"
#endif

/* The GPU uses byte offsets inside one 64 KiB AXI4-Lite aperture. The register
 * map, memory depths and wait settings come from the generated
 * gpgpu_platform.h. */

/* Largest memory in words: sizes the console's transfer buffer. */
#define GPGPU_MAX_WORDS \
    (GPGPU_IMEM_ENTRIES > GPGPU_DMEM_ENTRIES ? GPGPU_IMEM_ENTRIES : GPGPU_DMEM_ENTRIES)

/* Return codes. Misuse (bad index, GPU not idle, ...) is GPGPU_ERR_STATE. */
#define GPGPU_OK               0
#define GPGPU_ERR_STATE      (-1)
#define GPGPU_ERR_FAULT      (-2)  /* a kernel memory access failed; `clear` to acknowledge */
#define GPGPU_ERR_FATAL      (-3)  /* the memory subsystem locked up; needs gpgpu_reset() */

int gpgpu_init(void);
u32 gpgpu_read_status(void);
void gpgpu_print_status(void);
int gpgpu_start_and_wait(void);

/* Acknowledge STOPPED and FAULTED (W1C). A fatal fault stays until a reset. */
void gpgpu_clear(void);
/* Pulse the PL reset (FCLK_RESET0, which resets the GPU), then gpgpu_init(). */
int gpgpu_reset(void);

/* Addresses are WORD INDICES, not AXI byte addresses. */
int gpgpu_write_imem(u32 index, u32 word);
int gpgpu_write_dmem(u32 index, u32 word);
int gpgpu_read_imem(u32 index, u32 *data);
int gpgpu_read_dmem(u32 index, u32 *data);

int gpgpu_dump_imem_ascii(u32 offset, u32 count);
int gpgpu_dump_dmem_ascii(u32 offset, u32 count);

/* Compatibility stubs: the AXI MMIO map has no SP regfile window. */
int gpgpu_read_regfile(u32 index, u32 *data);
int gpgpu_dump_regfile_ascii(void);

#endif /* GPGPU_HOST_H */
