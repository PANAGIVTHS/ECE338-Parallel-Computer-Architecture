#ifndef GPGPU_RUNTIME_H
#define GPGPU_RUNTIME_H

#include <stdint.h>
#include "gpgpu_config.h"

/* Linker-provided symbols from linker.ld.  These are byte addresses from the
 * RISC-V core's point of view; host UART DMEM word offset = address / 4.
 *
 *   DMEM (BRAM, shared memory): GPGPU_ARGS, GPGPU_SHARED variables, the stacks
 *   GMEM (DDR): .rodata, .data and .bss, then __gmem_free_base.. for buffers
 */
extern volatile int __gpu_args_base[];
extern char __shared_start[];
extern char __shared_end[];
extern char __gpu_stack_bottom[];
extern char __stack_top[];
extern char __gmem_free_base[];
extern char __gmem_free_end[];

/* GPGPU_ARGS_WORDS words the host writes before a launch. */
#define GPGPU_ARGS   ((volatile int *)__gpu_args_base)

/* Shared memory, like CUDA's __shared__: the variable lives in DMEM (BRAM),
 * every lane sees the same one, and it is zero when the program loads. It
 * cannot have an initializer (the section is not loaded, only zeroed); use
 * .data (an ordinary initialized global, in GMEM) for initial values.
 *
 *   GPGPU_SHARED int table[64];
 */
#define GPGPU_SHARED __attribute__((section(".shared")))

/* DMEM byte address where .shared starts: right after GPGPU_ARGS, 16-byte
 * aligned (linker.ld). */
#define GPGPU_SHARED_BASE ((GPGPU_ARGS_WORDS * 4 + 15) & ~15)

/* One block of shared memory at exactly GPGPU_SHARED_BASE, placed before every
 * other GPGPU_SHARED variable: for a kernel that needs the addresses as
 * constants, e.g. to load with `lw rd, OFFSET(x0)` (terrain). One per program;
 * declaring it reserves the words, so no other variable lands there.
 *
 *   GPGPU_SHARED_FIXED int words[N];   // words[i] is at GPGPU_SHARED_BASE + 4 * i
 */
#define GPGPU_SHARED_FIXED __attribute__((section(".shared.fixed"), used))

/* Free GMEM after the compiler data, for buffers the program manages. */
#define GPGPU_GMEM_FREE ((volatile int *)__gmem_free_base)

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
 * The wrapper runs at PC 0, gives every lane a private GPGPU_STACK_STRIDE-byte
 * stack slice at the top of DMEM, calls kernel_main(), then requests completion with ECALL
 * service 0 (x17/a7 = 0). Ordinary RET/JALR instructions remain function returns.
 * a7 is caller-saved, not reserved: load the selector after kernel_main returns.
 * Other ECALL services currently do (nops)
 */
#define GPGPU_START(kernel_fn)                                                 \
    __attribute__((naked, noreturn, section(".text.start"))) void _start(void) \
    {                                                                          \
        __asm__ volatile(                                                      \
            "mv x5, x31\n"                                                     \
            "slli x6, x5, " GPGPU_STR(GPGPU_STACK_SHIFT) "\n"                  \
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
