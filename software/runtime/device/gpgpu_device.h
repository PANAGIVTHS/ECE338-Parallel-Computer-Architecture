#ifndef GPGPU_DEVICE_H
#define GPGPU_DEVICE_H

/*
 * The kernel side of the runtime (docs/runtime-spec.md, sections 5 and 6).
 *
 *   #include "gpgpu_device.h"
 *
 *   GPGPU_DEVICE int output[1024];
 *
 *   GPGPU_GLOBAL void my_kernel(int factor)
 *   {
 *       unsigned int i = gpgpu_block_idx_x() * gpgpu_block_dim() + gpgpu_thread_idx();
 *       output[i] = (int)i * factor;
 *   }
 *
 * The build reads the kernels and their parameters from the source (the scan
 * pass, with GPGPU_SCAN defined) and generates the entry code that loads the
 * parameters and runs the block loop (<p>_entry.c, which includes the source).
 */

#ifndef __riscv
#error "gpgpu_device.h is for kernels: compile them with the RISC-V toolchain"
#endif

#include "gpgpu_types.h"

/* ---- Markers ----------------------------------------------------------- */

#ifdef GPGPU_SCAN
/* Scan pass: each marker puts its object in a section of its own, so the
 * object file's symbols are the lists of kernels and exported variables. */
#define GPGPU_GLOBAL   __attribute__((used, noinline, section(".gpgpu_global")))
#define GPGPU_DEVICE   __attribute__((used, section(".gpgpu_device")))
#define GPGPU_CONSTANT __attribute__((used, section(".gpgpu_constant")))
#else
/* A kernel: a function returning void whose parameters are pointers or
 * integers of at most 32 bits. The entry code calls it for every block, and
 * it is inlined there. */
#define GPGPU_GLOBAL   static inline __attribute__((always_inline))
/* A global variable in GMEM that the host reaches by symbol. In .data, or in
 * .bss without a value, like any global; not static. */
#define GPGPU_DEVICE   __attribute__((used))
/* The same for a const variable, in .rodata. */
#define GPGPU_CONSTANT __attribute__((used))
#endif

/* Shared memory, like CUDA's __shared__: one copy for the 32 lanes of a block,
 * in the BRAM. Its contents are undefined when a block starts; no initializer. */
#define GPGPU_SHARED __attribute__((section(".shared")))

/* ---- Indices ----------------------------------------------------------- */

/* The launch block at GMEM_BASE (linker.ld): grid and parameters. */
extern const gpgpu_launch_block_t __gpu_launch[];

/* Block indices, set by the entry code before each block (section 6.2). The
 * kernels are compiled with -ffixed-x3 -ffixed-x4, and as global register
 * variables the compiler knows that they change from block to block. */
register uint32_t gpgpu_block_xy_ __asm__("tp"); /* x | y << 16 */
register uint32_t gpgpu_block_z_ __asm__("gp");

/* Lane in the block, 0 to GPGPU_NUM_CORES - 1: x31 (-ffixed-x31). */
static inline uint32_t gpgpu_thread_idx(void)
{
    uint32_t tid;
    __asm__("mv %0, x31" : "=r"(tid));
    return tid;
}

static inline uint32_t gpgpu_block_dim(void) { return GPGPU_NUM_CORES; }
static inline uint32_t gpgpu_block_idx_x(void) { return gpgpu_block_xy_ & 0xFFFFu; }
static inline uint32_t gpgpu_block_idx_y(void) { return gpgpu_block_xy_ >> 16; }
static inline uint32_t gpgpu_block_idx_z(void) { return gpgpu_block_z_; }
static inline uint32_t gpgpu_grid_dim_x(void) { return __gpu_launch[0].grid_x; }
static inline uint32_t gpgpu_grid_dim_y(void) { return __gpu_launch[0].grid_y; }
static inline uint32_t gpgpu_grid_dim_z(void) { return __gpu_launch[0].grid_z; }

/* Like __syncthreads(). The lanes run in lockstep, so today this only keeps
 * the compiler from moving memory accesses across it; with divergence or more
 * warps it becomes a real barrier. */
static inline void gpgpu_syncthreads(void)
{
    __asm__ volatile("" ::: "memory");
}

/* ---- Entry (generated code only) --------------------------------------- */

/* _start at PC 0: the lane's stack, then the kernel entry named by the launch
 * block, then completion (ECALL service 0). */
#define GPGPU_START_()                                                         \
    __attribute__((naked, noreturn, section(".text.start"))) void _start(void) \
    {                                                                          \
        __asm__ volatile(                                                      \
            "slli x6, x31, " GPGPU_STR(GPGPU_STACK_SHIFT) "\n"                 \
            "lui sp, %hi(__stack_top)\n"                                       \
            "addi sp, sp, %lo(__stack_top)\n"                                  \
            "sub sp, sp, x6\n"                                                 \
            "lui x5, %hi(__gpu_launch)\n"                                      \
            "lw x5, %lo(__gpu_launch)(x5)\n"                                   \
            "jalr x1, 0(x5)\n"                                                 \
            "li a7, 0\n"                                                       \
            "ecall\n");                                                        \
        __builtin_unreachable();                                               \
    }

/* The block loop of one kernel: z outermost, x innermost. The barriers keep
 * each block's memory accesses inside its iteration. */
#define GPGPU_BLOCK_LOOP_(call)                                                \
    do {                                                                       \
        const uint32_t grid_x_ = __gpu_launch[0].grid_x;                       \
        const uint32_t grid_y_ = __gpu_launch[0].grid_y;                       \
        const uint32_t grid_z_ = __gpu_launch[0].grid_z;                       \
        for (uint32_t z_ = 0; z_ < grid_z_; z_++)                              \
            for (uint32_t y_ = 0; y_ < grid_y_; y_++)                          \
                for (uint32_t x_ = 0; x_ < grid_x_; x_++) {                    \
                    gpgpu_block_xy_ = x_ | y_ << 16;                           \
                    gpgpu_block_z_ = z_;                                       \
                    __asm__ volatile("" ::: "memory");                         \
                    call;                                                      \
                    __asm__ volatile("" ::: "memory");                         \
                }                                                              \
    } while (0)

#endif /* GPGPU_DEVICE_H */
