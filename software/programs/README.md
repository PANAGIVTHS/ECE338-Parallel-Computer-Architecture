# GPGPU programs

Every program is a CUDA-like pair, written with the runtime of
[docs/runtime-spec.md](../../docs/runtime-spec.md): kernels in `<program>.c`
and a host program in `host.c` that launches them. Programs run in the
functional simulator on a PC and on the board through the UART monitor's
loader.

## Writing a program

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
./gpgpu software programs:<program>:host       # the A9 executable, against the platform's BSP
./gpgpu fpga programs:<program>:run            # send it to the board's monitor over UART and run it
```

On the board the monitor (`software/host/xc7z020/main.c`, deployed with
`./gpgpu fpga deploy`) receives the program over UART with `load`, runs it
with `run` and gets it back when `gpgpu_main` returns, without a reset. The
console output comes back to the PC, and the task's status is the program's.
The board needs a bitstream and a monitor built from this branch: an older
monitor has no `load` command.

With `software.host.boot_program: <program>` in the configuration,
`./gpgpu fpga deploy` starts that program in place of the monitor. Build it
first with `./gpgpu software programs:<program>:boot`: its arguments are
`software.runtime.arguments`, built in, and it stops when `gpgpu_main` returns.

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
<program>.map         its link map
<program>_dump_real.asm, <program>_program.asm   its disassembly and cleaned listing
<program>_sim         host.c with the runtime and the simulator, for this PC
<program>_a9.elf      host.c with the runtime and the board's backend, for the A9
<program>_boot_a9.elf the same, to run in place of the monitor (software.host.boot_program)
```

The simulator follows the hardware: lanes in lockstep, branches decided by
lane 0, memory faults. It also reports what the board would hide: a branch the
lanes disagree on, lanes storing different values to one DDR byte. Shared
memory holds `0xDEADBEEF` when a launch starts. With `GPGPU_SIM_FRAMES=<dir>`,
every `gpgpu_display()` writes the framebuffer there as a PPM picture.

Rules that come from the hardware:

- **Branches must be uniform.** Until divergence is implemented all lanes
  follow lane 0: a kernel computes per-lane choices with masks or arithmetic
  (`gpgpu_math.h`), and the problem size is a multiple of the 32 lanes (no
  per-lane `if (i < n)`).
- **Every array is its own pointer parameter**, and per-frame or per-call
  setup that is the same for every lane runs on the host and goes in through a
  `GPGPU_DEVICE` variable.
- `gpgpu_frames.h` is the host's frame loop for animated programs: draw into
  the framebuffer that is not shown, show it, report the frame rate.

## Memory spaces

`linker.ld` places the kernels in three memories; `architecture.memory` in
the configuration sets their sizes.

| Space | Memory | What | How a kernel uses it |
|---|---|---|---|
| `.text` | IMEM (BRAM), own addresses from 0 | code | — |
| `.shared` | SMEM (BRAM) from byte 0 | shared memory, undefined when a block starts, no initializers | `GPGPU_SHARED int t[64];` |
| stack | top of SMEM, `stack_bytes_per_lane` per lane | locals and spills, private per lane | ordinary locals |
| launch block | GMEM (DDR, 440 MiB by default) at `GMEM_BASE`, 256 bytes | entry, grid and parameters, written by the runtime | the kernel's parameters |
| `.rodata` | GMEM after the launch block | `const` tables, string literals | `static const int lut[] = {...};` |
| `.data` | GMEM after `.rodata` | initialized globals | `GPGPU_DEVICE int count = 100;` |
| `.bss` | GMEM after `.data` | zero-initialized globals | `GPGPU_DEVICE int slots[32];` |

- The runtime loads the data **once per module load**, with IMEM: it writes
  `.rodata`/`.data` into GMEM and zeroes `.bss`. Globals keep their values from
  one launch to the next, as in CUDA. The host reaches the ones marked
  `GPGPU_DEVICE` or `GPGPU_CONSTANT` with `gpgpu_memcpy_to/from_symbol`.
- Every lane sees the same globals: a global written by several lanes is a
  race, as on any GPU. Only locals (the stack) are per lane.
- GMEM is DDR: a load costs far more than a shared memory (BRAM) load. Data a
  kernel reads often belongs in `GPGPU_SHARED` memory, copied in by the block.
- Shared memory starts at address 0, so a shared pointer may be `NULL`: kernels
  must not test shared pointers against `NULL` (they build with
  `-fno-delete-null-pointer-checks`).
- `-fno-jump-tables` is the default: a `switch` becomes compares and branches.
  A kernel that wants a table (`.rodata`, so a DDR load per dispatch) asks
  with `__attribute__((optimize("jump-tables")))`, and the switch value must be
  the same in every lane.
- `GPGPU_SHARED_FIXED` reserves one block at `GPGPU_SHARED_BASE` (0), before
  the other shared variables, for kernels that need constant addresses
  (terrain).
- `memspaces` touches every space and its `host.c` checks them.

## Build directory

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

See [FPGA CLI flow](../../docs/fpga-cli.md) for the board machine's serial
configuration, permissions and UART ownership.
