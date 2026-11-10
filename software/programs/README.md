# GPGPU programs

## Structure

Each program lives in `software/programs/<program>/` and keeps only source inputs there. A program normally provides `<program>.c` with separate native and RISC-V paths selected by `__riscv`.

```c
#ifdef __riscv
int _start(void) {
    int threadIdx_x;
    __asm__ volatile("mv %0, x31" : "=r"(threadIdx_x));

    // RISC-V kernel code
}
#else
#include <stdio.h>
int main(void) {
    // Native reference implementation
}
#endif
```

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
└── <program>_instructions.mem
```

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

Each command includes its prerequisites: RISC-V build and IMEM generation →
SCP upload → verified binary IMEM load through the VM's UART → one kernel launch.
The compiler is incremental; remote actions repeat. The board must already be
programmed with the compatible host monitor. These tasks retain DMEM and do not
initialize program-specific arguments, export CSVs or visualize results.
See [FPGA CLI flow](../../docs/fpga-cli.md) for VM serial configuration,
permissions, UART ownership and failure handling. `run.sh` remains untouched.

The legacy `Makefile` uses the same output layout and accepts `BUILD_ROOT` as an override, but the `gpgpu` task runner is the authoritative config-driven entry point.
