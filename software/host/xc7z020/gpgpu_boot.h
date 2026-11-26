#ifndef GPGPU_BOOT_H
#define GPGPU_BOOT_H

/*
 * How the monitor and the programs it loads share the A9's DDR
 * (docs/runtime-spec.md, section 9.2):
 *
 *   0x0010_0000  the monitor: code, data, stacks and heap, 1 MiB minus 4 KiB
 *   0x001F_F000  the boot record, the last 4 KiB of the monitor's MiB
 *   0x0020_0000  the loaded program, up to the first framebuffer
 *
 * The monitor writes the program's arguments and its own resume address into
 * the boot record before it jumps to the program. The program's runtime reads
 * the arguments and, when gpgpu_main returns, writes the status and returns
 * to the monitor through the resume address.
 */

#include "xil_types.h"
#include "gpgpu_platform.h"

#define GPGPU_MONITOR_BASE        0x00100000U
#define GPGPU_MONITOR_BYTES       0x00100000U
#define GPGPU_BOOT_RECORD_BYTES   0x00001000U
#define GPGPU_BOOT_RECORD_ADDRESS (GPGPU_MONITOR_BASE + GPGPU_MONITOR_BYTES - GPGPU_BOOT_RECORD_BYTES)
#define GPGPU_PROGRAM_BASE        (GPGPU_MONITOR_BASE + GPGPU_MONITOR_BYTES)
#define GPGPU_PROGRAM_END         GPGPU_FB0_BASE

#define GPGPU_BOOT_MAGIC     0x42475047U /* "GPGB" */
#define GPGPU_BOOT_MAX_ARGS  32U
#define GPGPU_BOOT_ARGS_BYTES 3072U

typedef struct {
    u32 magic;   /* GPGPU_BOOT_MAGIC once the monitor has filled the record */
    u32 resume;  /* the monitor's resume function, void (*)(int status); 0: none */
    s32 status;  /* the program's exit status, written by the program */
    u32 argc;
    char args[GPGPU_BOOT_ARGS_BYTES]; /* argc strings, each ending in '\0' */
} gpgpu_boot_record_t;

_Static_assert(sizeof(gpgpu_boot_record_t) <= GPGPU_BOOT_RECORD_BYTES, "the boot record must fit its 4 KiB");

#define GPGPU_BOOT_RECORD ((volatile gpgpu_boot_record_t *)(UINTPTR)GPGPU_BOOT_RECORD_ADDRESS)

#endif /* GPGPU_BOOT_H */
