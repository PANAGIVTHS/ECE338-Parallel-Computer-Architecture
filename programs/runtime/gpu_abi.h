#ifndef GPU_ABI_H
#define GPU_ABI_H

/*
 * Host/GPU DMEM ABI.
 *
 * The RISC-V compiler emits byte addresses for lw/sw, while the UART host
 * monitor addresses DMEM as 32-bit words.  Therefore:
 *   C byte address 0x00000000 == UART DMEM word 0
 *   C byte address 0x00000100 == UART DMEM word 64
 *
 * The linker script provides the RISC-V symbols below so C code can refer to
 * fixed DMEM locations without hard-coding magic pointers in each program.
 */
#define GPU_ARG_WORDS 16
#define GPU_ARG_BASE_WORD 0
#define GPU_OUTPUT_BASE_WORD 64
#define GPU_STACK_STRIDE_BYTES 128
#define GPU_ARG_BASE_BYTE (GPU_ARG_BASE_WORD * 4)
#define GPU_OUTPUT_BASE_BYTE (GPU_OUTPUT_BASE_WORD * 4)

#ifdef __riscv
extern volatile int __gpu_args_base[];
extern volatile int __gpu_output_base[];
extern char __stack_top[];

#define GPU_ARGS   ((volatile int *)__gpu_args_base)
#define GPU_OUTPUT ((volatile int *)__gpu_output_base)
#else
#define GPU_ARGS   ((volatile int *)0)
#define GPU_OUTPUT ((volatile int *)0)
#endif

#endif
