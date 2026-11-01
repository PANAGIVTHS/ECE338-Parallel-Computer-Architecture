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

## Build

Use the task runner so compiler settings, `architecture.num_cores`, and `paths.build.root` come from the resolved configuration:

```bash
./gpgpu run software:programs:<program>:all
./gpgpu run software:programs:<program>:mem
```

Generated files are written to:

```text
<build-root>/software/programs/<program>/
├── <program>_x86
├── <program>.elf
├── <program>.map
├── <program>_dump_real.asm
├── <program>_program.asm
└── <program>_instructions.mem
```

The source directory is not used for generated artifacts. To select an external build root:

```bash
./gpgpu \
  --set paths.build.root=/workspace/gpgpu-build \
  run software:programs:<program>:all
```

The build root must not overlap the repository root or any source/config/tool
directory; unsafe values are rejected before task dispatch.

## FPGA execution through the VM

```bash
./gpgpu run fpga:programs:<program>:upload
./gpgpu run fpga:programs:<program>:load-imem
./gpgpu run fpga:programs:<program>:run
./gpgpu run fpga:programs:<program>:all
```

Each command includes its prerequisites: RISC-V build and IMEM generation →
SCP upload → verified binary IMEM load through the VM's UART → one kernel launch.
The compiler is incremental; remote actions repeat. The board must already be
programmed with the compatible host monitor. These tasks retain DMEM and do not
initialize program-specific arguments, export CSVs or visualize results.
See [FPGA CLI flow](../../docs/fpga-cli.md) for VM serial configuration,
permissions, UART ownership and failure handling. `run.sh` remains untouched.

The legacy `Makefile` uses the same output layout and accepts `BUILD_ROOT` as an override, but the `gpgpu` task runner is the authoritative config-driven entry point.
