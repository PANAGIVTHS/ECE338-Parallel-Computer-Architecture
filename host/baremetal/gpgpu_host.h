#ifndef GPGPU_HOST_H
#define GPGPU_HOST_H

#include "xil_types.h"

#define IMEM_WORDS 2048
#define DMEM_WORDS 2048
#define REG_WORDS  32
#define MAX_WORDS (IMEM_WORDS > DMEM_WORDS ? IMEM_WORDS : DMEM_WORDS)

int gpgpu_init(void);

u32 gpgpu_read_status(void);
void gpgpu_print_status(void);

int gpgpu_write_imem(u32 addr, u32 word);
int gpgpu_write_dmem(u32 addr, u32 word);

int gpgpu_read_imem(u32 addr, u32 *data);
int gpgpu_read_dmem(u32 addr, u32 *data);
int gpgpu_read_regfile(u32 addr, u32 *data);

int gpgpu_start_and_wait(void);
int gpgpu_finish_readback(void);

int gpgpu_dump_imem_ascii(u32 offset, u32 count);
int gpgpu_dump_dmem_ascii(u32 offset, u32 count);
int gpgpu_dump_regfile_ascii(void);

#endif
