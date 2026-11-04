#ifndef GPGPU_HOST_H
#define GPGPU_HOST_H

#include "xil_types.h"

/* Physical AXI base assigned in Vivado Address Editor. Override if needed. */
#ifndef GPGPU_BASEADDR
#define GPGPU_BASEADDR 0x43C00000U
#endif

/* The GPU uses byte offsets inside one 64 KiB AXI4-Lite aperture. */
#define GPGPU_REG_INFO         0x0000U
#define GPGPU_REG_CONTROL      0x0004U
#define GPGPU_REG_STATUS       0x0008U
#define GPGPU_REG_IRQ_ENABLE   0x000CU
#define GPGPU_REG_IRQ_STATUS   0x0010U
#define GPGPU_IMEM_BASE        0x2000U
#define GPGPU_DMEM_BASE        0x4000U

#define GPGPU_CONTROL_START    0x00000001U
#define GPGPU_CONTROL_STOP     0x00000002U
#define GPGPU_STATUS_IDLE      0x00000001U
#define GPGPU_STATUS_RUNNING   0x00000002U
#define GPGPU_STATUS_STOPPED   0x00000004U

#define IMEM_WORDS             2048U
#define DMEM_WORDS             2048U
#define MAX_WORDS              2048U

/* Set to 0 to wait by polling REG_IRQ_STATUS, rather than a PS interrupt.
 * IRQ mode assumes the GPU is wired to Zynq IRQ_F2P[0] (GIC ID 61).
 */
#ifndef GPGPU_USE_IRQ
#define GPGPU_USE_IRQ         1
#endif
#ifndef GPGPU_IRQ_ID
#define GPGPU_IRQ_ID          61U
#endif
#ifndef GPGPU_WAIT_LIMIT
#define GPGPU_WAIT_LIMIT      100000000U
#endif

int gpgpu_init(void);
u32 gpgpu_read_status(void);
void gpgpu_print_status(void);
int gpgpu_start_and_wait(void);

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
