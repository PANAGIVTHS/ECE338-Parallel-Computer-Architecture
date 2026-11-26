# GPGPU programs

There are two kinds of programs:

- **Runtime programs** have a `host.c`: kernels in `<program>.c`, written with
  the runtime of [docs/runtime-spec.md](../../docs/runtime-spec.md), and a host
  program that launches them like a CUDA program. `memspaces` is the first.
  They run in the functional simulator on a PC; the board follows in phase 2.
- **Kernel programs** have no `host.c`: one kernel with `GPGPU_ARGS`, run by
  the UART tools (`fpga_run.py`). The sections after this one are about them.

## Runtime programs

```text
software/programs/<program>/
├── <program>.c   kernels: GPGPU_GLOBAL functions, GPGPU_DEVICE and GPGPU_SHARED variables
├── <program>.h   optional: types and constants both sides use
└── host.c        int gpgpu_main(int argc, char **argv)
```

```c
/* <program>.c */
#include "gpgpu_device.h"

GPGPU_DEVICE int output[4096];

GPGPU_GLOBAL void my_kernel(int factor)
{
    unsigned int i = gpgpu_block_idx_x() * gpgpu_block_dim() + gpgpu_thread_idx();
    output[i] = (int)i * factor;
}

/* host.c */
#include "gpgpu.h"
#include "<program>_kernels.h"

int gpgpu_main(int argc, char **argv)
{
    static int result[4096];
    GPGPU_CHECK(gpgpu_launch(my_kernel, gpgpu_dim3(4096 / GPGPU_BLOCK_SIZE), 3));
    GPGPU_CHECK(gpgpu_memcpy_from_symbol(result, <program>_sym_output, sizeof result, 0));
    return result[5] == 15 ? 0 : 1;
}
```

```bash
./gpgpu software programs:<program>:sim        # build, then run gpgpu_main in the simulator
./gpgpu --set 'software.runtime.arguments=["8"]' software programs:<program>:sim
./gpgpu software programs:<program>:all        # kernels, their listing and the simulator program
./gpgpu software runtime:check                 # the simulator against the Python model, every RTL case
```

The build scans the kernels (`<program>:kernels`), generates their entry code
and launch functions, links the kernels and turns them into the module
(`<program>:module`), which the host program carries. It stops on what the
hardware cannot run: a parameter that is not a pointer or an integer of at
most 32 bits, a division or high multiply, a call chain deeper than the lane's
128-byte stack, an initializer on a shared variable. Generated files, in
`<build-root>/software/programs/<program>/`:

```text
<program>_entry.c     the entry function and block loop of every kernel (RISC-V)
<program>_kernels.h   gpgpu_launch(<kernel>, ...) and <program>_sym_<variable>, for host.c
<program>_module.c    IMEM and GMEM images, kernel entries, variable addresses
<program>.elf         the kernels, linked with linker.ld
<program>_sim         host.c with the runtime and the simulator, for this PC
```

The simulator follows the hardware: lanes in lockstep, branches decided by
lane 0, memory faults. It also reports what the board would hide: a branch the
lanes disagree on, lanes storing different values to one DDR byte. Shared
memory holds `0xDEADBEEF` when a launch starts. With `GPGPU_SIM_FRAMES=<dir>`,
every `gpgpu_display()` writes the framebuffer there as a PPM picture.

## Kernel programs

Each program lives in `software/programs/<program>/` and keeps only source inputs there. A program normally provides `<program>.c` with separate native and RISC-V paths selected by `__riscv`.

```c
#ifdef __riscv
#include "../gpgpu_runtime.h"

void kernel_main(void) {
    unsigned int tid = gpgpu_thread_id();

    // RISC-V kernel code; ordinary C returns to the wrapper.
}
GPGPU_START(kernel_main)
#else
#include <stdio.h>
int main(void) {
    // Native reference implementation
}
#endif
```

`GPGPU_START` places `_start` at PC 0, initializes a private per-lane stack,
then calls the kernel as a normal function. After it returns, the wrapper loads
`a7` (`x17`) with service number 0 and executes `ecall` to complete the kernel;
a defensive infinite loop follows. Other service numbers are currently no-ops.
`a7` remains an ordinary caller-saved ABI register, not a fixed/reserved
register. A `ret` / `jalr x0,0(x1)` only returns from a function and does not
signal completion. Custom entrypoints must use the same service-0 ECALL
sequence at their real termination sites.

Assembly and IMEM generation retain the complete linked instruction listing,
including subroutines after RET or ECALL instructions; neither instruction is
an image boundary.

## Memory spaces

`linker.ld` places a kernel in three memories; `architecture.memory` in the
configuration sets their sizes (see `docs/memory-layout.html` to try values).

| Space | Memory | What | How a kernel uses it |
|---|---|---|---|
| `.text` | IMEM (BRAM), own addresses from 0 | code | — |
| `GPGPU_ARGS` | DMEM byte 0, `args_words` words | host-written arguments | `GPGPU_ARGS[i]` |
| `.shared` | DMEM after the args | shared memory, zero at load, no initializers | `GPGPU_SHARED int t[64];` |
| stack | top of DMEM, `stack_bytes_per_lane` per lane | locals and spills, private per lane | ordinary locals |
| `.rodata` | GMEM (DDR) from `GMEM_BASE` | `const` tables, string literals | `static const int lut[] = {...};` |
| `.data` | GMEM after `.rodata` | initialized globals | `int count = 100;` |
| `.bss` | GMEM after `.data` | zero-initialized globals | `int slots[32];` |
| free GMEM | `__gmem_free_base` .. `__gmem_free_end` | program buffers | `GPGPU_GMEM_FREE` |

- The host loads the data **once per program load**, with IMEM: it writes
  `.rodata`/`.data` into GMEM and zeroes `.bss` and `.shared`. Globals keep
  their values from one launch to the next, as in CUDA after a module load.
- Every lane sees the same globals: a global written by several lanes is a
  race, as on any GPU. Only locals (the stack) are per lane.
- GMEM is DDR: a load costs far more than a DMEM (BRAM) load. Tables a kernel
  reads often belong in `GPGPU_SHARED` memory, filled by the kernel or the host.
- `-fno-jump-tables` is the default: a `switch` becomes compares and branches.
  A kernel that wants a table (`.rodata`, so a DDR load per dispatch) asks
  with `__attribute__((optimize("jump-tables")))`, and the switch value must be
  the same in every lane.
- `GPGPU_SHARED_FIXED` reserves one block at `GPGPU_SHARED_BASE`, before the
  other shared variables, for kernels that need constant addresses (terrain).
- Host adapters find a variable through `<program>_layout.json`:
  `self.symbol("name")` and `self.symbol_window("name")` in `fpga.py`.
- `memspaces`, a runtime program, touches every space of the runtime and its
  `host.c` checks them.

## Build

Use the task runner so compiler settings, `architecture.num_cores`, and `paths.build.root` come from the resolved configuration:

```bash
./gpgpu software programs:<program>:all
./gpgpu software programs:<program>:mem
```

Generated files are written to:

```text
<build-root>/software/programs/<program>/
├── <program>_x86
├── <program>.elf
├── <program>.map
├── <program>_dump_real.asm
├── <program>_program.asm
├── <program>_instructions.mem   IMEM image
├── <program>_gmem.mem           .rodata/.data, '<byte address> <word>' (an RTL case's ddr_seed.mem format)
└── <program>_layout.json        GPGPU_ARGS, .shared, stacks, .bss and every global's address
```

`linker_layout.ld` (the MEMORY regions, from `architecture.memory` and the RTL)
is written once for all programs to `<build-root>/software/programs/`.

The source directory is not used for generated artifacts. To select an external build root:

```bash
./gpgpu \
  --set paths.build.root=/workspace/gpgpu-build \
  software programs:<program>:all
```

The build root must not overlap the repository root or any source/config/tool
directory; unsafe values are rejected before task dispatch.

## FPGA execution through the VM

```bash
./gpgpu fpga programs:<program>:upload
./gpgpu fpga programs:<program>:load-imem
./gpgpu fpga programs:<program>:run
./gpgpu fpga programs:<program>:all
```

Each command includes its prerequisites: RISC-V build, IMEM and data images →
SCP upload → verified IMEM and GMEM data load through the VM's UART → one kernel launch.
The compiler is incremental; remote actions repeat. The board must already be
programmed with the compatible host monitor. These tasks do not write
program-specific arguments, export CSVs or visualize results; `fpga_run.py`
with the program's `fpga.py` adapter does.
See [FPGA CLI flow](../../docs/fpga-cli.md) for VM serial configuration,
permissions, UART ownership and failure handling. `run.sh` remains untouched.
