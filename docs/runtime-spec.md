# GPGPU runtime specification

Version 0.4, 2026-11-26.

**Status: design.** Nothing here is implemented unless it is marked *(exists)*. *(prototyped)* means that the
construct was compiled with the project's compilers but is not in the repository.

## 1. Purpose

Today a program runs on the board through a chain of PC tools: `fpga_run.py`, a per-program `fpga.py` adapter,
`uart.py` and the commands of the UART monitor. The host side of every application is Python on another machine, and
a kernel call is a series of word writes over UART.

This specification defines a programming model like CUDA's:

- A program is a kernel in C for the GPU and a host program in C for the ARM Cortex-A9 of the Zynq.
- The host program uses a runtime API to copy data to and from GPU memory and to launch kernels.
- The build embeds the GPU code and its initialized data in the host executable. The runtime loads them.
- No script knows where a program keeps its arguments, data or results.

**Out of scope for this version:** loading large data sets (language model weights, game data), the port of DOOM,
Ethernet and SD card support, dynamic allocation of GPU memory, launch queues and streams, atomics, `printf` from a kernel, several SMs, and
branch divergence itself.

## 2. Terms

| Term | Meaning in this project | CUDA |
|---|---|---|
| Device | The GPGPU in the PL: one SM with 32 lanes that execute the same instruction | GPU |
| Host | The Cortex-A9, core 0, bare metal | CPU |
| Lane, thread | One SP. Its index is in `x31` | thread |
| Block | The 32 threads that run together. The block size is always `GPGPU_NUM_CORES` | thread block |
| Grid | The blocks of one launch, up to three dimensions. They run one after another | grid |
| Kernel | A C function marked `GPGPU_GLOBAL` | `__global__` function |
| Program | A directory of `software/programs`: kernels, one host program, one shared header | a `.cu` file and its executable |
| Module | The GPU code and data of one program, as C data linked into its host executable | cubin, fatbin |
| Launch | One run of one kernel over a grid | `kernel<<<grid, block>>>(...)` |
| Launch block | The 256 bytes in GMEM that describe a launch: entry address, grid, parameters | parameter buffer in the constant bank |
| Kernel generator | The build step that reads the signatures of the kernels and writes their entry code and launch functions | part of `nvcc` |
| Shared variable | A variable marked `GPGPU_SHARED`: one copy per block, seen by its 32 lanes | `__shared__` variable |
| Device pointer | A C pointer to GMEM or to a framebuffer | device pointer |
| Symbol | The host's handle of a `GPGPU_DEVICE` or `GPGPU_CONSTANT` variable: address and size | the variable's name |

## 3. Memory

### 3.1 Spaces

A physical memory (which RAM) is not the same as an address space (who can see it, and for how long). This table
lists the address spaces.

| Space | Declared with | Physical memory | Visible to | Initial contents | Lifetime | CUDA |
|---|---|---|---|---|---|---|
| Code | kernel functions | IMEM, BRAM | instruction fetch only | module load | module | code |
| Parameters | parameters of a `GPGPU_GLOBAL` function | GMEM, launch block | all lanes, read only | every launch | one launch | constant bank |
| Global | `GPGPU_DEVICE` or a plain global | GMEM | all lanes, host if `GPGPU_DEVICE` | module load | module | `__device__` |
| Constant | `GPGPU_CONSTANT` or `const` | GMEM | all lanes read only, host if `GPGPU_CONSTANT` | module load | module | `__constant__` |
| Shared | `GPGPU_SHARED` | shared memory, BRAM | the 32 lanes of a block | **undefined** | one block | `__shared__` |
| Local | automatic variables, spills | registers, then shared memory BRAM | one lane | undefined | one call | local memory |
| Framebuffers | `gpgpu_framebuffer(n)` | DDR | lanes write only, host, display | undefined | always | none |

### 3.2 Who does what

| Region | Size and position set by | Written by | Read by |
|---|---|---|---|
| IMEM | config `imem_bytes` | runtime, at module load | instruction fetch |
| Launch block | this document, `linker.ld` | runtime, at every launch | `_start` and the kernel entry |
| Constants and globals | compiler and linker, limit the size of GMEM | runtime at load, kernels, host by symbol | kernels, host by symbol |
| `GPGPU_SHARED` variables | compiler and linker, limit `shared_bytes` minus the stacks | kernels | kernels |
| Stacks | config `stack_bytes_per_lane` | each lane its own | the same lane |
| Framebuffers | `gpu_pkg` | kernels, host | display DMA, host |

### 3.3 Shared memory

The on-chip data BRAM, named DMEM in the current RTL, is called **shared memory** everywhere: RTL (`SMEM_*`),
configuration (`shared_bytes`), generated host headers and documentation. The parameters leave it. From byte 0 it
holds the `GPGPU_SHARED` variables, and the stacks are at its top.

- The host never reads or writes shared memory during normal operation. The AXI4-Lite window stays for debugging.
- Its contents are undefined when a block starts. Nothing may be carried from one block or launch to the next.
- An initializer on a `GPGPU_SHARED` variable is a build error. The linker cannot detect one in a NOLOAD section,
  so the module builder must check.
- The BRAM serves two accesses per cycle. A load by 32 lanes takes about 20 cycles (measured), not one.
- `GPGPU_SHARED_FIXED` (terrain) *(exists)* stays, with `GPGPU_SHARED_BASE` equal to 0. Address 0 is then a valid
  address of a variable, so kernels must not test shared pointers against `NULL`.

**The stacks stay in this BRAM for now**, 128 bytes per lane. They are logically local memory. Kernels may not assume
where the stack is, so it can move without changing a kernel. The planned home is one BRAM per lane (32 RAMB18,
16 of the 124 free BRAM tiles, 2 KiB per lane, all lanes in parallel). DDR is rejected: without address interleaving
the 128-byte stacks put each lane in a different 128-byte burst group, so one spill is 32 bursts.

### 3.4 Global memory (GMEM)

GMEM is DDR that host and device reach at the same addresses. From `GMEM_BASE`:

```
GMEM_BASE            launch block, 256 bytes
GMEM_BASE + 0x100    constants and globals           up to the end of GMEM
```

All device buffers are global variables, placed by the linker. There is no dynamic allocation in this version, so the
compiler data may fill GMEM and the setting `gmem_data_bytes` goes away. A program that does not fit fails to link.
The linker script defines `__gpu_launch` and the data sections.

### 3.5 DDR map

`architecture.memory.host_bytes` is the size of the host region. It determines the rest:

| Region | Rule | Default (`host_bytes` ends at 64 MiB) |
|---|---|---|
| Host: loader and program | `0x0010_0000` to `host_bytes` | `0x0010_0000`, 63 MiB |
| FB0 | `host_bytes` | `0x0400_0000` |
| FB1 | FB0 + 4 MiB | `0x0440_0000` |
| GMEM | FB1 + 4 MiB, to the end of the 512 MiB | `0x0480_0000`, 440 MiB |

`host_bytes` must be a multiple of 8 MiB, so the RTL decodes GMEM with the upper address bits only. `rtl:config`
writes the three bases and `GMEM_SIZE` to `gpu_config_pkg.sv`.

Today FB0 is `0x1800_0000`, FB1 `0x1840_0000` and GMEM `0x1880_0000` with 8 MiB *(exists)*. The change of map needs a
new bitstream and is phase 5 (section 12). Everything before it works with both maps, because all addresses come
from `gpgpu_platform.h` and `linker_layout.ld`.

The A9 linker script currently claims all 512 MiB, so nothing stops the host program from growing into the
framebuffers. The build must end the host region at FB0.

### 3.6 Cache coherency

The GPU reads and writes DDR through an HP port, which does not see the A9 caches. The rules are:

- The host touches GMEM only through the runtime. Device pointers are ordinary C pointers, so the compiler accepts a
  host dereference, but it is an error, as in CUDA.
- A copy to the device invalidates the range, copies, then flushes the range. The first step matters at unaligned
  ends: a cache line there may hold stale neighbours that the GPU has changed since.
- A copy from the device invalidates the range, then copies.
- The same holds for a copy or fill of a framebuffer: the display reads DDR and does not see the caches either.
- A launch flushes the launch block, then executes a `dsb` before the START write.

Flush and invalidate are internal to the runtime and not part of the API. Only the bytes that are copied are handled, so
a launch without a copy costs nothing extra. Copies wait for the running kernel, so the host cannot use a buffer while
a kernel does. Direct access by the host is future work (`GPGPU_MANAGED`, section 15).

### 3.7 Memory ordering on the device

- The lanes of a block run in lockstep. A store instruction completes in all lanes before the next instruction starts.
- Two lanes that store to the same shared word in one instruction: the highest lane wins. In DDR the winner is
  unspecified.
- The compiler may reorder and keep values in registers, as for any C program. `gpgpu_syncthreads()` is a compiler
  barrier that prevents it.
- Correct kernels call `gpgpu_syncthreads()` wherever CUDA needs `__syncthreads()`. With divergence or several warps
  it will become a real barrier, and kernels that rely on lockstep will break.

## 4. Program structure

```
software/
  runtime/
    include/gpgpu_types.h      types for both sides
    device/gpgpu_device.h      kernel side: indices, spaces, _start
    host/gpgpu.h               host API
    host/                      runtime, backends: xc7z020/ and sim/
  programs/<p>/
    <p>.h                      optional: types and constants that both sides use
    <p>.c                      kernels (RISC-V)
    host.c                     host program (A9 or PC)

build/software/programs/<p>/
    <p>_entry.c                generated: entry code of every kernel (RISC-V)
    <p>_kernels.h              generated: launch functions and symbols, included by host.c
    <p>_module.c               generated: the module (A9 or PC)
```

In generated C names a `-` in the program name becomes `_`.

### 4.1 Complete example

`my_program.h`

```c
#define N 4096 /* a multiple of the block size */
```

`my_program.c`

```c
#include "gpgpu_device.h"
#include "my_program.h"

GPGPU_DEVICE int input[N];
GPGPU_DEVICE int output[N];

GPGPU_GLOBAL void my_kernel(int factor)
{
    unsigned int i = gpgpu_block_idx_x() * gpgpu_block_dim() + gpgpu_thread_idx();

    output[i] = input[i] * factor;
}
```

`host.c`

```c
#include "gpgpu.h"
#include "my_program_kernels.h" /* generated, includes my_program.h */

int gpgpu_main(int argc, char **argv)
{
    static int h_input[N], h_output[N];

    for (int i = 0; i < N; i++)
        h_input[i] = i;

    GPGPU_CHECK(gpgpu_memcpy_to_symbol(my_program_sym_input, h_input, sizeof h_input, 0));
    GPGPU_CHECK(gpgpu_launch(my_kernel, gpgpu_dim3(N / GPGPU_BLOCK_SIZE), 3));
    GPGPU_CHECK(gpgpu_memcpy_from_symbol(h_output, my_program_sym_output, sizeof h_output, 0)); /* waits */

    for (int i = 0; i < N; i++)
        if (h_output[i] != 3 * i)
            return 1;
    return 0;
}
```

The launch is `my_kernel<<<N / 32, 32>>>(3)` in CUDA. The block size is not an argument, because it is
always 32.

The host program defines `gpgpu_main`; the runtime owns `main`, because the A9 startup code always passes
`argc = 0` and the runtime has to fetch the arguments (section 9.2). The value that `gpgpu_main` returns is the result of
the program: 0 is success.

## 5. Kernel side

### 5.1 Defining kernels

A kernel is a C function that returns `void` and is marked `GPGPU_GLOBAL`. It is defined in `<p>.c`, is not declared
anywhere else and is written once. Functions that kernels call are ordinary C functions and need no marker.

A program may define any number of kernels, with names unique in the program. Together they must fit IMEM (16 KiB).
`return` in a kernel ends that block, not the launch. A kernel may change its parameters; the change is lost at the end
of the block.

Parameter rules:

- A parameter is a data pointer, or an integer of at most 32 bits.
- `float`, 64-bit integers, structs by value and function pointers are rejected at build time.
- A larger value goes through a buffer, and the pointer to it is the parameter.
- A kernel has at most 56 parameters.
- A type that a parameter points to must be a C type, or be defined in `<p>.h`, because the host sees it too.

The build adds to `<p>.c` what `nvcc` adds to a CUDA kernel *(prototyped: a generator of about 45 lines of Python,
compiled with the RISC-V, ARM and x86 compilers; not run)*:

1. **Scan.** `<p>.c` is compiled with `-DGPGPU_SCAN -aux-info`. In this pass `GPGPU_GLOBAL` places a function in a
   marker section of the object file, so the object's symbols are the list of kernels. `-aux-info` makes GCC write the
   prototype of every function, so no C parser is needed. An error in a kernel is reported here, at its line in `<p>.c`.
2. **Entry code.** `<p>_entry.c` includes `<p>.c` and adds `__gpgpu_kernel_<kernel>` for each kernel: it loads the
   parameters and the grid and calls the kernel for every block. In this pass `GPGPU_GLOBAL` is
   `static inline __attribute__((always_inline))`, so the call disappears. The kernel ELF is built from this file.
3. **Host header.** `<p>_kernels.h` has a typed function `<kernel>_launch(grid, ...)` for each kernel and the symbols of
   section 5.3. It includes `<p>.h` if there is one.

`-aux-info` is a GCC option for C: kernels are C, and the RISC-V compiler is GCC. Until a program has been built once,
an editor does not find `<p>_kernels.h`.

### 5.2 Indices and grid

| Function | Value | Read from | Cost | CUDA |
|---|---|---|---|---|
| `gpgpu_thread_idx()` | lane in the block, 0 to 31 | `x31` | 0 or 1 instruction | `threadIdx.x` |
| `gpgpu_block_dim()` | `GPGPU_NUM_CORES` | constant | none | `blockDim.x` |
| `gpgpu_block_idx_x()` | block in the grid | `tp`, lower 16 bits | 2 instructions | `blockIdx.x` |
| `gpgpu_block_idx_y()` | block in the grid | `tp`, upper 16 bits | 1 instruction | `blockIdx.y` |
| `gpgpu_block_idx_z()` | block in the grid | `gp` | 0 or 1 instruction | `blockIdx.z` |
| `gpgpu_grid_dim_x()`, `_y()`, `_z()` | blocks of the launch | launch block, GMEM | 1 DDR load | `gridDim` |

All of them are `static inline` functions of `gpgpu_device.h`. Threads in a block have one dimension. A block index is
the same in the 32 lanes of a block. The launch block is `const`, so the compiler keeps a grid dimension in a register:
in the example below it is loaded once for each z *(prototyped)*.

A launch over `gpgpu_dim3(4, 2)` has 8 blocks. They run in the order B0 to B7:

```
                 block_idx_x
                  0   1   2   3
block_idx_y  0  [B0][B1][B2][B3]      grid_dim_x = 4
             1  [B4][B5][B6][B7]      grid_dim_y = 2
                                      grid_dim_z = 1
```

The generated entry code sets the indices before each block:

```c
for (z = 0; z < grid_z; z++)
    for (y = 0; y < grid_y; y++)
        for (x = 0; x < grid_x; x++) {
            tp = x | y << 16;
            gp = z;
            my_kernel(factor); /* inlined */
        }
```

Example: an image of 1280 x 720 pixels, launched over `gpgpu_dim3(1280 / 32, 720)`, one block for every 32 pixels of
a row:

```c
GPGPU_GLOBAL void image(unsigned int *fb)
{
    unsigned int x = gpgpu_block_idx_x() * gpgpu_block_dim() + gpgpu_thread_idx(); /* 0 to 1279 */
    unsigned int y = gpgpu_block_idx_y();                                          /* 0 to 719 */
    unsigned int width = gpgpu_grid_dim_x() * gpgpu_block_dim();                   /* 1280 */

    fb[y * width + x] = x ^ y;
}
```

**`gpgpu_dim3`.** The host gives the grid as a `gpgpu_dim3_t`. Each dimension is 1 to 65535, because two indices share
one register. CUDA's `dim3` is a C++ constructor with default values; C has neither, so `gpgpu_dim3` is a macro that
chooses by the number of arguments. Both are in `gpgpu_types.h` *(prototyped)*:

```c
typedef struct { uint32_t x, y, z; } gpgpu_dim3_t;

#define GPGPU_DIM3_1_(x)       ((gpgpu_dim3_t){ x, 1, 1 })
#define GPGPU_DIM3_2_(x, y)    ((gpgpu_dim3_t){ x, y, 1 })
#define GPGPU_DIM3_3_(x, y, z) ((gpgpu_dim3_t){ x, y, z })
#define GPGPU_DIM3_PICK_(a, b, c, macro, ...) macro
#define gpgpu_dim3(...) \
    GPGPU_DIM3_PICK_(__VA_ARGS__, GPGPU_DIM3_3_, GPGPU_DIM3_2_, GPGPU_DIM3_1_, 0)(__VA_ARGS__)
```

A missing dimension is 1. More than three arguments are a compile error. There is no `gpgpu_dim2`.

### 5.3 Declarations

| Declaration | Section | Meaning |
|---|---|---|
| `GPGPU_SHARED T x[N];` | `.shared` | shared memory, no initializer |
| `GPGPU_DEVICE T x = v;` | `.data`, or `.bss` without a value | GMEM, exported to the host |
| `GPGPU_CONSTANT const T x[] = {...};` | `.rodata` | GMEM, read only for kernels, exported to the host |
| `T x;`, `static T x = v;` | `.bss`, `.data` | GMEM, private to the kernels |
| `const T x[] = {...}` | `.rodata` | GMEM, private to the kernels |

`GPGPU_DEVICE` and `GPGPU_CONSTANT` variables must not be `static`. The compiler keeps them even if no kernel uses
them. All static globals keep their values from one launch to the next, until the module is reloaded. `GPGPU_DEVICE`
marks variables only, not functions. An array without a value costs nothing in the program image.

The two markers work like `GPGPU_GLOBAL`: only in the scan pass do they place a variable in a marker section, which
gives the list of exported names *(prototyped)*.

The host reaches an exported variable through its symbol, `<p>_sym_<name>`, declared in `<p>_kernels.h`:

```c
/* my_program.c */
GPGPU_DEVICE int offset = 0;

/* host.c */
int value = 5;
GPGPU_CHECK(gpgpu_memcpy_to_symbol(my_program_sym_offset, &value, sizeof value, 0));
```

A kernel uses the variable by name. When a kernel takes a pointer instead, for example to swap two buffers between
launches, the host passes `gpgpu_symbol_address(symbol)`.

### 5.4 Restrictions

1. **Branches must be uniform.** Until divergence is implemented all lanes follow lane 0. The CUDA idiom
   `if (i < n)` is not uniform when `n` is not a multiple of 32. Round `n` up and pad the buffers.
2. **No division, remainder or high multiply.** The compiler emits them for `/`, `%` and 64-bit products, also when
   dividing by many constants. Only `mul` is implemented. The module builder rejects code with other M instructions.
   High multiply is expected soon (#31).
3. No floating point.
4. 128 bytes of stack per lane. Large arrays and recursion are not possible.
5. Jump tables are off by default (`-fno-jump-tables`) *(exists)*.
6. Constants and parameters are DDR loads. Copy a value that is used often into a variable, or a small table into
   shared memory.

## 6. Device ABI

### 6.1 Launch block

At `GMEM_BASE`, 256 bytes, little endian words:

| Word | Field | Contents |
|---|---|---|
| 0 | `entry` | IMEM byte address of the kernel entry |
| 1, 2, 3 | `grid_x`, `grid_y`, `grid_z` | 1 to 65535 each |
| 4 | `abi_version` | 1, for debugging |
| 5-7 | reserved | 0 |
| 8-63 | parameters | one word each, in order |

A parameter narrower than 32 bits is extended to a word by the host. The kernel reads the low bytes.
There is one launch block, at a fixed address, so there can be one launch at a time.

### 6.2 Registers

| Register | At START | During a kernel |
|---|---|---|
| `x31` | lane index, read only | lane index (`-ffixed-x31`) |
| `sp` | 0 | `__stack_top - lane * stack_bytes_per_lane`, set by `_start` |
| `tp` (`x4`) | 0 | `block_x + block_y * 65536` |
| `gp` (`x3`) | 0 | `block_z` |
| others | 0 | RISC-V ilp32 convention |

Keeping the three indices separate avoids a division.

**Why `tp` and `gp` are free.** The RISC-V ABI reserves `x3` as the global pointer and `x4` as the thread pointer, and
calls both unallocatable: a compiler never keeps ordinary values in them. They have one purpose each, and neither
exists here:

| Register | Purpose in the ABI | Why it does not arise |
|---|---|---|
| `gp` (`x3`) | The linker may replace an absolute address with an offset from `gp` (linker relaxation) | `-mno-relax` *(exists)*, and `linker.ld` does not define `__global_pointer$` |
| `tp` (`x4`) | Base of thread-local variables (`__thread`) | not supported: the toolchain has no TLS, and its emulation does not link with `-nostdlib` |

The reservation is made explicit, so it does not depend on those defaults:

1. The kernels are compiled with `-ffixed-x3 -ffixed-x4`, like `-ffixed-x31` today.
2. `gpgpu_device.h` declares the two as global register variables. This also tells the compiler that their value
   changes from one block to the next, so it does not move a read out of the block loop:

   ```c
   register uint32_t gpgpu_block_xy_ __asm__("tp");
   register uint32_t gpgpu_block_z_ __asm__("gp");
   ```

3. `-mno-relax` stays. The option in 1 does not stop the linker, which acts after the compiler.
4. The module builder rejects a program whose object file of the scan pass writes `x3` or `x4`. That object has the
   kernels but not the entry code. This finds inline assembly, which the compiler does not check.

With 1 to 3, code under heavy register pressure used neither register *(prototyped)*. `gp`-relative small data stays
disabled for good.

### 6.3 Start and end

`_start` is at PC 0. It sets `sp`, loads `entry` from the launch block and jumps to it with `jalr`. The entry function
loads the grid and the parameters once, then runs the body for every block, z outermost and x innermost. When it
returns, `_start` executes `ecall` with `a7 = 0`.

There is one START and one completion interrupt per launch, whatever the grid size. No RTL change is needed.

For small test kernels, GCC inlined the body into the block loop and used no stack. The parameters were loaded
before the loop. A kernel with many live values will still spill *(prototyped)*.

A fault ends the whole launch. The fault report has the PC and the lanes, not the block index.

## 7. Module

### 7.1 Contents

`software:programs:<p>:module` turns the kernel ELF into `<p>_module.c`, which defines what `<p>_kernels.h` declares:

| Item | From |
|---|---|
| IMEM image | `.text` |
| GMEM image | `.rodata`, `.data` |
| `.bss` range, data limit | linker symbols |
| `const uint32_t <kernel>_entry` | symbols `__gpgpu_kernel_<kernel>` |
| `const gpgpu_symbol_t <p>_sym_<name>` | names from the scan pass, addresses and sizes from the ELF |
| Architecture: lanes, IMEM and shared memory bytes, GMEM base, ABI version | config and RTL constants |

A program has exactly one module. The builder checks:

- every instruction is one the RTL implements;
- no `GPGPU_SHARED` variable has an initializer;
- no kernel writes `x3` or `x4` (section 6.2);
- the sizes fit; the linker already checks the regions *(exists)*.

### 7.2 Loading

The runtime loads the module before `gpgpu_main`. It checks the hardware registers (`INFO`, `INFO_MEM`,
`INFO_FEATURES`) against the module. A mismatch ends the program with a message that names both values. It then writes
IMEM, copies the GMEM image, clears `.bss` and flushes both ranges. Shared memory is not touched.

`gpgpu_module_reload()` repeats this to restore the initial values of the static globals.

## 8. Host API

Every function returns `gpgpu_error_t` unless noted. `GPGPU_CHECK(call)` prints the error, file and line, then ends
the program with status 1.

### 8.1 Device

| Function | Meaning | CUDA |
|---|---|---|
| `gpgpu_get_properties(gpgpu_properties_t *)` | lanes, clock, memory sizes, RTL build | `cudaGetDeviceProperties` |
| `gpgpu_synchronize()` | wait for the running launch and return its error | `cudaDeviceSynchronize` |
| `gpgpu_query()` | `GPGPU_SUCCESS` when idle, `GPGPU_ERROR_NOT_READY` while a kernel runs | `cudaStreamQuery` |
| `gpgpu_reset()` | reset the PL, reload the module | `cudaDeviceReset` |
| `gpgpu_module_reload()` | section 7.2 | none |
| `const char *gpgpu_error_string(gpgpu_error_t)` | text of an error | `cudaGetErrorString` |
| `gpgpu_get_fault(gpgpu_fault_t *)` | cause, status kinds, lanes and PC of the last fault | none |

### 8.2 Memory

| Function | Meaning | CUDA |
|---|---|---|
| `gpgpu_memcpy(void *dst, const void *src, size_t bytes, kind)` | `GPGPU_HOST_TO_DEVICE`, `GPGPU_DEVICE_TO_HOST`, `GPGPU_DEVICE_TO_DEVICE` | `cudaMemcpy` |
| `gpgpu_memset(void *dst, int value, size_t bytes)` | fill device memory | `cudaMemset` |
| `gpgpu_memcpy_to_symbol(symbol, src, bytes, offset)` | write a `GPGPU_DEVICE` or `GPGPU_CONSTANT` variable | `cudaMemcpyToSymbol` |
| `gpgpu_memcpy_from_symbol(dst, symbol, bytes, offset)` | read one | `cudaMemcpyFromSymbol` |
| `void *gpgpu_symbol_address(symbol)` | device pointer of a variable; never waits | `cudaGetSymbolAddress` |

Except for `gpgpu_symbol_address`, all of them wait for the running launch first. If that launch failed, they return
its error and do nothing else. Device ranges must lie inside the symbol, the program's data in GMEM or a framebuffer.

> **Planned:** `gpgpu_malloc` and `gpgpu_free` are not in this version (section 15).

### 8.3 Launch

```c
gpgpu_error_t gpgpu_launch(kernel, gpgpu_dim3_t grid, <parameters of the kernel>);
```

`gpgpu_launch` is a macro that calls the generated function `<kernel>_launch`. The compiler checks the number and the
types of the parameters. A wrong pointer type is a diagnostic, and an error under `-Werror`.

`gpgpu_dim3` builds the grid (section 5.2). A launch:

1. Waits for the previous launch. If it failed, returns its error and launches nothing.
2. Checks the grid. A zero or too large dimension is `GPGPU_ERROR_INVALID_VALUE`.
3. Writes and flushes the launch block.
4. Clears and enables the completion interrupt, writes START and returns.

The call is asynchronous with one slot: the host can work while one kernel runs. The second launch waits for the first.

### 8.4 Errors

| Error | Meaning | Afterwards |
|---|---|---|
| `GPGPU_SUCCESS` | | |
| `GPGPU_ERROR_INVALID_VALUE` | bad argument, range or pointer | nothing happened |
| `GPGPU_ERROR_INCOMPATIBLE` | module and hardware differ | program ends |
| `GPGPU_ERROR_NOT_READY` | only from `gpgpu_query` | |
| `GPGPU_ERROR_FAULT` | a kernel access failed | reported once, then cleared; a new launch is allowed |
| `GPGPU_ERROR_TIMEOUT` | the kernel ran too long and was stopped | reported once, then cleared |
| `GPGPU_ERROR_FATAL` | the memory subsystem locked up, or the GPU did not stop | every call returns it until `gpgpu_reset()` |

A launch error is returned by the first call that waits. The contents of global variables after a
fault or timeout are undefined.

**Timeout.** `software.host.launch_timeout_ms`, 0 for none, counts from START. A waiting call that sees it expire
writes STOP, waits a short fixed time for IDLE and clears the STOPPED latch. The limit is checked only while the host
waits. Today the driver waits forever *(exists)*.

### 8.5 Display, console, performance

| Function | Meaning |
|---|---|
| `unsigned int *gpgpu_framebuffer(int n)` | device pointer of framebuffer 0 or 1 |
| `gpgpu_display(int n)` | show framebuffer `n` from the next frame; waits for the running launch |
| `int gpgpu_key(void)` | the next key from the console, or -1 |
| `uint32_t gpgpu_time_ms(void)` | time since start |
| `gpgpu_printf(...)` | console output |
| `gpgpu_perf_read(gpgpu_perf_t *)` | counters of the last launch; waits *(driver exists)* |

## 9. Running programs

### 9.1 Two ways to run

| Target | Host code | Kernel | Result |
|---|---|---|---|
| Board | A9 executable | the GPGPU | console over UART |
| PC simulator | x86 executable of the same `host.c` | the same RISC-V module in the functional simulator | console, framebuffers as PPM files |

### 9.2 UART loader

There is one A9 executable per program. The monitor stays resident on the board and loads programs, so a new program
needs no reset and no bitstream.

```
0x0010_0000   monitor and loader, 1 MiB, with the boot record in its last 4 KiB
0x0020_0000   the loaded program, up to FB0
```

The PC tool sends the loadable segments of the ELF, not the file. Protocol:

1. `load <entry> <segments>`, then for each segment the address, size, CRC-32 and data. The monitor rejects a segment
   outside the program region before it receives data, and checks each CRC.
2. `run <arguments>`. The monitor writes the arguments and its return address into the boot record.
3. The monitor disables interrupts, cleans the data caches and jumps to the entry. Cleaning is required: the program's
   startup code invalidates the caches without writing them back.
4. The program starts normally: its own vectors, MMU table, stack and `.bss`. The runtime initializes the GPU and the
   interrupt controller, loads the module, reads the arguments from the boot record and calls `gpgpu_main`.
5. When `gpgpu_main` returns, the runtime waits for the GPU, stops interrupts, prints
   `GPGPU_EXIT <status>`, cleans the caches and returns to the monitor. The monitor restores its own vectors, MMU
   table and stack.

A program that crashes or hangs the A9 needs `fpga deploy`. Steps 3 and 5 are the part of this design with the most
risk and must be tried on the board first.

At 115200 baud 72 KB, the size of the current host image, takes 6 to 7 seconds. Input data is linked into the program. Large
data waits for an SD card or Ethernet.

### 9.3 Monitor

| Stays | Removed |
|---|---|
| `help`, `status`, `perf`, `clear`, `reset`, `display`, `gmemcheck` and its fill | `loadimem*`, `loaddmem*`, `loadgmem_bin` |
| single word read and write, dumps | `fillgmem`, `filldmem`, `bench` |
| new: `load`, `run` | the old `run` |

With `software.host.boot_program` set, `fpga deploy` sends that program in place of the monitor. This replaces the
autorun header. Such a program has no monitor to return to and stops when `gpgpu_main` returns.

### 9.4 Commands

| Command | Action |
|---|---|
| `./gpgpu software programs:<p>:kernels` | `<p>_entry.c` and `<p>_kernels.h` |
| `./gpgpu software programs:<p>:module` | kernel ELF and module |
| `./gpgpu software programs:<p>:host` | A9 executable |
| `./gpgpu software programs:<p>:sim` | build for the PC and run |
| `./gpgpu fpga programs:<p>:run` | build, send over UART, run, show the console, return the program's status |
| `./gpgpu fpga deploy` | bitstream and monitor, as today |

Arguments come from `software.programs.arguments.<p>` or `--set`. The UART tool knows the loader protocol and
nothing about the program.

The A9 executable is meant to be linked with `arm-none-eabi-gcc` directly against the exported board support package,
without one Vitis component per program. If that does not work, the fallback is one component per program, as
`feature/doom` does.

## 10. Functional simulator

A library in C that executes the module's RISC-V code with the rules of `gpgpu_model.py`: lockstep lanes, branches
from lane 0, address decoding and faults. It implements the same backend interface as the board, so `host.c` and the
runtime do not change.

- GMEM and the framebuffers are mapped at their board addresses. Pointers are equal on both targets. Mapping GMEM
  at its address was tried on Linux for both DDR maps.
- Host pointers are 64-bit; launch parameters are 32-bit. The runtime rejects a pointer parameter that does not fit.
- It reports errors that the board would hide: a branch that the lanes disagree on, lanes that store different values
  to one DDR byte, unimplemented instructions.
- It fills shared memory with a pattern when a launch starts, so a kernel that depends on its contents fails.
  The pattern is per launch and not per block, because the block loop runs on the device.
- It does not model time, and it does not model caches. A missing flush cannot be found with it.

It is validated against the Python model: both must produce the same registers, memory and faults on every RTL case.

## 11. Migration

| Item | Change |
|---|---|
| `fpga_run.py`, `*/fpga.py`, load paths of `program_uart.py` and `uart.py` | removed |
| `visualize.py` of nbody and differences | reads results printed by the host program |
| `gpgpu_autorun.h` and its generator | removed |
| `GPGPU_ARGS`, `GPGPU_START`, `args_words` | removed; C parameters and `GPGPU_GLOBAL` |
| native x86 `main()` in the kernels | removed once the program runs in the simulator; a reference computation moves to `host.c` |
| cube, metaballs, julia, mandelbrot, terrain, ripple | the frame number is a parameter; the host counts frames |
| nbody, nbody-3d | state moves from shared memory to `GPGPU_DEVICE` arrays |
| differences | input in a `GPGPU_DEVICE` array instead of shared memory |
| memspaces | results in a `GPGPU_DEVICE` array; `call_count` becomes `GPGPU_DEVICE` |
| simple, stress, memfault, stacktest, subword | buffer addresses become pointer parameters |
| RTL cases compiled from C (test46) | regenerated, launch block in `ddr_seed.mem` |
| DOOM | after it merges; its `gp_gmem_*` and `gp_gpu_*` calls map to this API |

## 12. Implementation order

Each phase ends with all RTL suites passing and is its own pull request. Phases 1 to 4 need no RTL change.

| Phase | Contents | Done when |
|---|---|---|
| 1 | Device ABI, kernel generator, module builder, host runtime, simulator; memspaces only | memspaces passes in the simulator, and the simulator agrees with the Python model on all cases |
| 2 | A9 build, UART loader, `fpga programs:<p>:run` | memspaces passes on the board, twice in a row without a reset, and a second program loads after it |
| 3 | The other programs | every program passes in the simulator and on the board |
| 4 | Removal of the old flow, documentation | no reference to the removed tools remains |
| 5 | RTL: DDR map from config, 440 MiB GMEM, `DMEM` to `SMEM`, `interface_version` 4 | all suites pass, the bitstream meets timing, all programs pass on the board |

Until phase 4 the old flow works for the programs that have not moved. For that time `linker.ld` keeps the `.args`
region for programs that use `GPGPU_ARGS`, and gives the launch block its place in GMEM for all.

Phase 5 depends on timing: the build of 2026-11-23 misses the 40 MHz clock by 0.106 ns with 84 % of the LUTs in use.
`perf/timing-closure` should merge first. `feature/doom` changes `GMEM_SIZE` on the same line.

## 13. Decisions

| Topic | Decision |
|---|---|
| GMEM | 440 MiB by default, from `host_bytes` in the config |
| Parameters | in GMEM at a fixed address; 32-bit values and pointers only |
| Stack | stays in the BRAM; one BRAM per lane later |
| Name of the BRAM | shared memory everywhere |
| Shared memory contents | undefined at block start |
| Host program | one A9 executable per program, bare metal |
| Files | `<p>.c`, `host.c`, optional `<p>.h` |
| Kernel definition | ordinary C function marked `GPGPU_GLOBAL`; a build step generates the rest |
| Launch | `gpgpu_launch(kernel, grid, ...)`, type checked |
| Markers | `GPGPU_GLOBAL`, `GPGPU_DEVICE`, `GPGPU_SHARED`, `GPGPU_CONSTANT` |
| Grid | three dimensions; block loop on the device |
| Kernels per program | many, selected by entry address |
| Synchronization | asynchronous, one slot |
| Device pointers | ordinary C pointers |
| Host access to globals | only `GPGPU_DEVICE` and `GPGPU_CONSTANT` |
| Device buffers | static `GPGPU_DEVICE` arrays; dynamic allocation later |
| Cache coherency | inside `gpgpu_memcpy*` and `gpgpu_memset`; `GPGPU_MANAGED` later |
| Program loading | UART loader |
| Large data | deferred to SD card or Ethernet |
| Errors | reported once; timeout from the config; only a fatal error needs a reset |
| Names | `gpgpu_snake_case` |
| PC testing | new functional simulator in C |
| Monitor | debug tool and loader only |
| Atomics, kernel `printf` | not in this version |

## 14. Open points

| Point | How it is settled |
|---|---|
| Cost of a parameter load from DDR | measure in phase 1 with the RTL bench; a constant bank in RTL if it matters |
| Return from a program to the monitor | try on the board at the start of phase 2; fallback is a deploy per program |
| Link without a Vitis component | try at the start of phase 2 |
| Baud rate above 115200 | try in phase 2 |
| Timing of the stack BRAMs | separate RTL experiment after phase 5 |

## 15. Future

**Dynamic allocation.** `gpgpu_malloc` and `gpgpu_free`, as in CUDA, will be added later: buffers whose size is known
only at run time, taken from the part of GMEM that the program's globals leave free. Kernels will receive them as
pointer parameters, which they can already take, so existing kernels do not change. The allocator is not specified
yet.

**Managed variables.** `GPGPU_MANAGED` variables, like `__managed__` in CUDA: the host reads and writes them directly,
without a copy. Useful for large data that should not exist twice.

```c
/* my_program.c */
GPGPU_DEVICE  int table[N]; /* host: only through gpgpu_memcpy_*, no cost at launch */
GPGPU_MANAGED int state[N]; /* host: direct access, cache work at launch and synchronize */

/* host.c */
int *state = gpgpu_symbol_address(my_program_sym_state);

state[0] = 5;                            /* the host writes directly */
GPGPU_CHECK(gpgpu_launch(my_kernel, gpgpu_dim3(N / GPGPU_BLOCK_SIZE))); /* flushes the managed variables */
GPGPU_CHECK(gpgpu_synchronize());        /* waits, then invalidates the managed variables */
gpgpu_printf("%d\n", state[0]);          /* the host reads directly */
```

- The host must not touch a managed variable from the launch until `gpgpu_synchronize()` returns. Nothing prevents it:
  a write in that time may be lost, or damage what the kernel wrote in the same cache line.
- The flush is in `gpgpu_launch`, before START. The invalidate is in `gpgpu_synchronize`, after the kernel ends, because
  the A9 may load lines speculatively while the kernel runs.
- The invalidate covers the managed range only. Invalidating the whole cache would lose host variables that are not in
  DDR yet, including the stack.
- The linker places managed variables together, aligned and padded to the 32-byte cache line, so the runtime knows the
  range. A program without any pays nothing.
- The cost is paid at every launch and must be measured: the Xilinx range functions work line by line, and 1 MiB is
  32768 lines. Flushing the whole cache before START is safe and may be faster for large ranges.
