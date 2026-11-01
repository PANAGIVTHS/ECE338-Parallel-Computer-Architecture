#ifndef GPGPU_RUNTIME_H
#define GPGPU_RUNTIME_H

#include <stdint.h>
#include "gpgpu_config.h"

/* Linker-provided DMEM symbols from gpgpu.ld.  These are byte addresses from
 * the RISC-V core's point of view; host UART DMEM word offset = address / 4. */
extern volatile int __gpu_args_base[];
extern char __gpu_stack_bottom[];
extern char __stack_top[];

#define GPGPU_ARGS   ((volatile int *)__gpu_args_base)

#define GPGPU_STACK_STRIDE 64u

static inline __attribute__((always_inline)) unsigned int gpgpu_thread_id(void)
{
    unsigned int tid;
    __asm__ volatile("mv %0, x31" : "=r"(tid));
    return tid;
}

/* Use this for normal C kernels that may spill registers.
 *
 * Example:
 *
 *   static void kernel_main(void) {
 *       unsigned int tid = gpgpu_thread_id();
 *       ... ordinary C that may use the stack ...
 *   }
 *   GPGPU_START(kernel_main)
 *
 * The wrapper runs at PC 0, gives every lane a private 64-byte stack slice at
 * the top of DMEM, calls kernel_main(), then requests completion with ECALL
 * service 0 (x17/a7 = 0). Ordinary RET/JALR instructions remain function returns.
 * a7 is caller-saved, not reserved: load the selector after kernel_main returns.
 * Other ECALL services currently do (nops)
 */
#define GPGPU_START(kernel_fn)                                                 \
    __attribute__((naked, noreturn, section(".text.start"))) void _start(void) \
    {                                                                          \
        __asm__ volatile(                                                      \
            "mv x5, x31\n"                                                     \
            "slli x6, x5, 6\n"                                                 \
            "lui sp, %hi(__stack_top)\n"                                       \
            "addi sp, sp, %lo(__stack_top)\n"                                  \
            "sub sp, sp, x6\n"                                                 \
            "jal x1, " #kernel_fn "\n"                                         \
            "li a7, 0\n"                                                       \
            "ecall\n"                                                          \
        );                                                                     \
        __builtin_unreachable();                                               \
    }

#endif /* GPGPU_RUNTIME_H */
