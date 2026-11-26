# ECE338-Parallel-Computer-Architecture

## The gpgpu CLI

`./gpgpu <category> <task>` builds, tests and operates everything below; the categories are
`vivado`, `vitis`, `fpga`, `rtl` and `software`. Run `./gpgpu <category> --help` to list the
tasks. See [tools/gpgpu/README.md](tools/gpgpu/README.md) for its structure, tab completion
and how to add a command.

## SMX RTL simulation (Verilator)

The CLI SMX flow requires Verilator, GNU make, and a C++ compiler. Configure
`tools.verilator.command`, `tools.make.command`, and `tools.native_cxx.command`
in `config/local.yaml` for machine-specific installations. Icarus/vvp are not
used. Python dependencies are initialized by `./gpgpu` (using uv when available).

```bash
./gpgpu rtl smx:build
./gpgpu rtl smx:run
./gpgpu rtl smx:all
./gpgpu --set tests.rtl.random.iterations=3 --set tests.rtl.random.seed=12345 rtl random
./gpgpu --set tests.rtl.trace.enabled=true rtl smx:all
./gpgpu rtl smx:wave
```

`architecture.num_cores` controls both expected-memory generation and the compiled
bench parameter.

### Test cases and the GPGPU model

A case is `tests/hardware/rtl/cases/test<N>/program.asm`, with optional
`dmem_seed.mem` (initial DMEM: hex words, `@<word index>` moves on) and
`ddr_seed.mem` (initial DDR: `<byte address> <word>` hex pairs).
`rtl:generate` assembles each case to `program.mem` and runs that machine
code on the GPGPU model (`tools/tests/gpgpu_model.py`) to produce the expected
`regfile_c<lane>.mem`, `data.mem` and, for a case that uses DDR, `ddr.mem`
(`bursts <n>` and the expected DDR words). The model follows the hardware's
rules: lockstep lanes that branch with lane 0, the kernel ending at lane 0's
RET, the memory map and permissions of `MemorySubsystemPkg::decode_access`,
ascending-lane order for same-word DMEM stores, and one AXI burst per group per
store instruction. A case must end with a halt ecall without a fault; a branch the lanes
disagree on or lanes storing different values to one DDR word in one
instruction is reported. Every constant comes from the RTL packages:
`rtl:constants` elaborates them with pyslang into
`<paths.build.root>/tests/rtl/rtl_constants.txt` (`pkg::NAME=value`). Without
the DDR backend (`architecture.ddr_enable: false`), the benches skip cases that
have a `ddr.mem`. Each suite compiles every `hardware.sources.extensions` file
under `paths.rtl.sources.gpgpu`, minus its own `tests.rtl.<suite>.exclude_sources`
(directory or file names), with `hardware.sources.ordered` first (packages and
interfaces before their users; excluded entries are dropped).
`hardware.sources.header_extensions` files are cache dependencies only. The bench and top module come from
`tests.rtl.<suite>.testbench` and `tests.rtl.<suite>.top`. Every bench attaches the
AXI4 slave model `tests.rtl.axi_slave.source` (compiled before the bench) to the
GPGPU's DDR master; `tests.rtl.axi_slave.parameters` set its latency, READY/VALID
rates and seed. `tests.rtl.<suite>.parameters` override HDL parameters for one
suite. Headers next to a bench (`tb_e2e_host.svh`) are found with `-I` and tracked.

Generated C++, objects, the native `main` binary, `build.log`, and `simulation.log`
stay under `<paths.build.root>/tests/rtl/smx/`. Runtime uses this directory with
a `cases` link to the test inputs, so pipeline timing diagram `trace.csv` files
remain in `tests/hardware/rtl/cases/test*/`. `tests.rtl.trace.enabled` (all suites, off
by default, since it slows builds and runs; set it to true to write waveforms)
adds `tests.rtl.trace.verilator_flags` at compile time and passes
`+DUMP_FILE=<tests.rtl.trace.dump_file>` at runtime; the dump lands in the suite's
build directory, and every run first removes the previous one. The default flags
(`--trace-fst --trace-structs`) split packed structs into named fields and keep
enum state names. `rtl:<suite>:wave` opens the dump of the suite's last traced run
in Surfer (`tools.surfer.command`) and returns at once, so the window does not
block other commands; it does not run the suite. `--plain` keeps console output
without the monitor.
The build cache tracks sources, headers, compiler command/options, make, C++
compiler, and core count. Random testing reuses the same compiled executable,
prints reproducible seeds, logs to `<paths.build.root>/tests/rtl/random/random.log`,
and preserves the first failing `cases/test999` input.

### E2E (AXI4-Lite)

```bash
./gpgpu rtl e2e:all
./gpgpu --set tests.rtl.trace.enabled=true rtl e2e:all
```

The bench file and top module come from `tests.rtl.e2e.testbench` and
`tests.rtl.e2e.top`. The bench instantiates the AXI4-Lite wrapper (the IP top
used on the FPGA) and touches the GPGPU only through AXI4-Lite and the IRQ pin. It first checks the
CSR map and error responses, plus a host-only DMEM write/readback. Then, for
each case, it clears DMEM, loads and verifies IMEM, enables the IRQ, writes
`CONTROL.START`, waits for the completion IRQ, checks `STATUS`/`IRQ_STATUS` and
the W1C acknowledge, and compares all of DMEM with the expected data file and, for a
DDR case, the DDR model's contents and burst count with `ddr.mem`. Register files are
not host-visible, so they are checked only by the SMX suite. Its
`tests.rtl.e2e.exclude_sources` keeps `interfaces/` (the AXI wrapper) that the SMX suite
excludes. Every bench setting (case root, case prefix and first index, program
and data file names, clock period, reset length, timeouts, unmapped
address, INFO version) is a required plusarg taken from `tests.rtl.e2e.plusargs`.
The bench has no defaults and stops if any is missing; add `TEST_END` to stop
early. The aggregate
`rtl:{build,run,all}` tasks cover every suite.

### DDR (AXI4 master)

```bash
./gpgpu rtl ddr:all
```

The DDR bench shares the E2E harness (`tests/hardware/rtl/tb_e2e_host.svh`: the
AXI4-Lite top, the slave model, host tasks and RISC-V encoders) and is built
with `DDR_ENABLE=1` from `tests.rtl.ddr.parameters`. Its kernels only store to
the framebuffers (the DDR read path is not implemented yet): consecutive words,
one group per lane (more groups than write slots), gaps carrying `WSTRB=0`, the
same word from every lane, a store loop, and SLVERR/DECERR injection checked
through `FAULT_INFO`/`FAULT_LANES`/`FAULT_PC`. Results are read through the
model's backdoor, with burst counts and an idle bus checked after each kernel.
Then it runs every directed case, DDR cases included.
`tests.rtl.range` in `config/profiles/default.yaml` selects directed SMX/E2E
case IDs: `"all"` (default) or an inclusive range such as `"1-10"` or `"5-5"`.
For a one-off selection:

```bash
./gpgpu --set tests.rtl.range=1-10 rtl smx:all
```

The range is passed as `+TEST_IDX` / `+TEST_END` at runtime, without recompiling
the bench. Explicit ranges with missing case sources fail before simulation.
Shared input generation still prepares all cases; random testing is unaffected.

### Kernel termination (ECALL)

The runtime's `_start` initializes each lane's stack and calls the kernel's
entry (docs/runtime-spec.md), which runs the kernel over the grid's blocks,
then executes `li a7, 0; ecall` after its normal return. `a7` (`x17`) is not
reserved; it is read through the usual forwarding and hazard paths at ECALL.
Only service 0 requests termination. Unsupported or mixed lane service values
currently act as non-terminating no-ops. Normal RET/JALR instructions never
signal completion, and loaders retain linked functions after RET or ECALL.

On an accepted exit, the resident warp stops fetching/issuing and discards
younger instructions. Older lane writeback and memory responses drain before
the existing completion/status/IRQ path fires. No divergence or additional
resident warps are implemented; exit state is warp-scoped for future extension.

Run the focused host-driven, compiled-C, directed SMX/AXI, and seeded random
regressions with Verilator and a RISC-V bare-metal GCC on `PATH`:

```bash
python tests/hardware/rtl/ecall/run.py --cores 4 32
```

Build products, copied cases, disassembly, logs, and `results.json` stay under
`build/tests/ecall-current/`. See `tests/hardware/rtl/ecall/README.md` for coverage
and verification limits.

## Running programs

A program is a CUDA-like pair in `software/programs/<program>/`: kernels in
`<program>.c` and a host program in `host.c` that launches them
([docs/runtime-spec.md](docs/runtime-spec.md),
[software/programs/README.md](software/programs/README.md)). The same host
program runs on a PC, with the functional simulator in place of the GPU, and
on the board's A9, loaded over UART by the monitor:

```bash
./gpgpu software programs:nbody:sim                                   # on this PC
./gpgpu --set 'software.runtime.arguments=["1000","10"]' fpga programs:nbody:run   # on the board
./gpgpu --set 'software.runtime.arguments=["300","1","csv"]' software programs:nbody:sim > nbody.txt
python3 software/programs/nbody/visualize.py --input nbody.txt
```

The board needs the bitstream and the monitor first (`./gpgpu fpga deploy`);
programs then load one after another without a reset. See
[docs/fpga-cli.md](docs/fpga-cli.md) for the board's tasks, and for a program
that runs in place of the monitor (`software.host.boot_program`).
