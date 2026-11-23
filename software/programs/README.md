# GPGPU programs

## Structure

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
- `memspaces` touches every space and checks them; its `fpga.py` verifies them
  on the board.

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
