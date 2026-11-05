# ECE338-Parallel-Computer-Architecture

## SMX RTL simulation (Verilator)

The CLI SMX flow requires Verilator, GNU make, and a C++ compiler. Configure
`tools.verilator.command`, `tools.make.command`, and `tools.native_cxx.command`
in `config/local.yaml` for machine-specific installations. Icarus/vvp are not
used. Python dependencies are initialized by `./gpgpu` (using uv when available).

```bash
./gpgpu run tests:rtl:smx:build
./gpgpu run tests:rtl:smx:run
./gpgpu run tests:rtl:smx:all
./gpgpu --set tests.rtl.random.iterations=3 --set tests.rtl.random.seed=12345 run tests:rtl:random
./gpgpu --set tests.rtl.trace.enabled=true run tests:rtl:smx:all
```

`architecture.num_cores` controls both expected-memory generation and the compiled
bench parameter.

### Test cases and the GPGPU model

A case is `tests/hardware/rtl/cases/test<N>/program.asm`, with optional
`dmem_seed.mem` (initial DMEM: hex words, `@<word index>` moves on) and
`ddr_seed.mem` (initial DDR: `<byte address> <word>` hex pairs).
`tests:rtl:generate` assembles each case to `program.mem` and runs that machine
code on the GPGPU model (`tools/tests/gpgpu_model.py`) to produce the expected
`regfile_c<lane>.mem`, `data.mem` and, for a case that uses DDR, `ddr.mem`
(`bursts <n>` and the expected DDR words). The model follows the hardware's
rules: lockstep lanes that branch with lane 0, the kernel ending at lane 0's
RET, the memory map and permissions of `MemorySubsystemPkg::decode_access`,
ascending-lane order for same-word DMEM stores, and one AXI burst per group per
store instruction. A case must end with RET without a fault; a branch the lanes
disagree on or lanes storing different values to one DDR word in one
instruction is reported. Every constant comes from the RTL packages:
`tests:rtl:constants` elaborates them with pyslang into
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
remain in `tests/hardware/rtl/cases/test*/`. Enabling `tests.rtl.trace.enabled` (all suites)
adds `tests.rtl.trace.verilator_flags` at compile time and passes
`+DUMP_FILE=<tests.rtl.trace.dump_file>` at runtime; the dump lands in the suite's
build directory. The default flags (`--trace-fst --trace-structs`) split packed
structs into named fields and keep enum state names; open the dump with Surfer or
GTKWave. `--plain` keeps console output without the monitor.
The build cache tracks sources, headers, compiler command/options, make, C++
compiler, and core count. Random testing reuses the same compiled executable,
prints reproducible seeds, logs to `<paths.build.root>/tests/rtl/random/random.log`,
and preserves the first failing `cases/test999` input.

### E2E (AXI4-Lite)

```bash
./gpgpu run tests:rtl:e2e:all
./gpgpu --set tests.rtl.trace.enabled=true run tests:rtl:e2e:all
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
and data file names, clock period, reset length, timeouts, RET encoding, unmapped
address, INFO version) is a required plusarg taken from `tests.rtl.e2e.plusargs`.
The bench has no defaults and stops if any is missing; add `TEST_END` to stop
early. The aggregate
`tests:rtl:{build,run,all}` tasks cover every suite.

### DDR (AXI4 master)

```bash
./gpgpu run tests:rtl:ddr:all
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
./gpgpu --set tests.rtl.range=1-10 run tests:rtl:smx:all
```

The range is passed as `+TEST_IDX` / `+TEST_END` at runtime, without recompiling
the bench. Explicit ranges with missing case sources fail before simulation.
Shared input generation still prepares all cases; random testing is unaffected.
