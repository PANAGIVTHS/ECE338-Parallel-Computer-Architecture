# Testing the RTL

The tests simulate the RTL with Verilator, and compare the results with a software
model of the GPU. They need Verilator, GNU make, a C++ compiler and nothing from
Xilinx. If your installation is not on `PATH`, set `tools.verilator.command`,
`tools.make.command` and `tools.native_cxx.command` in `config/local.yaml`.

| Suite | What it drives | What it checks |
| --- | --- | --- |
| `smx` | The GPU directly | Registers of every lane, DMEM, DDR |
| `e2e` | The AXI4-Lite top, like the host on the FPGA | The register map, errors, the interrupt, DMEM, DDR |
| `ddr` | The same top, with the DDR backend always on | DDR loads and stores, bursts, AXI errors |
| `random` | Random programs on the `smx` bench | The same as `smx` |

## Run the tests

```bash
./gpgpu rtl smx:all       # generate, build and run one suite
./gpgpu rtl all           # every directed suite
./gpgpu rtl random
```

Each suite also has `smx:build` and `smx:run`, for one stage. To run only some of the
directed cases, give an inclusive range. The bench is not recompiled:

```bash
./gpgpu --set tests.rtl.range=1-10 rtl smx:all
```

A range that names a missing case fails before the simulation. The range does not
affect `random`, which prints its seed, so that you can repeat a run:

```bash
./gpgpu --set tests.rtl.random.iterations=3 --set tests.rtl.random.seed=12345 rtl random
```

`random` keeps the input of the first failure in `cases/test999`.

`architecture.num_cores` sets the number of lanes, in the benches and in the expected
results.

## Look at waveforms

```bash
./gpgpu --set tests.rtl.trace.enabled=true rtl smx:all
./gpgpu rtl smx:wave      # open the last traced run in Surfer
```

The default Verilator flags split packed structs into named fields and keep the names
of enum values. A run without tracing removes the previous dump, so a dump always
belongs to the last run.

## Where the results are

Everything built is under `<paths.build.root>/tests/rtl/<suite>/`: the simulator,
`build.log`, `simulation.log` and the waveform. The generated inputs and expected
results are next to each case, and git ignores them.

> **Note:** Git also keeps ignored files when you switch branches. If
> `./gpgpu rtl generate` fails on a case that your branch does not have, delete that
> case's directory.

## Test cases

A case is a directory `tests/hardware/rtl/cases/test<N>/`. The numbers must be
consecutive: the benches stop at the first missing one.

| File | Written by | What it is |
| --- | --- | --- |
| `program.asm` | You | The program, in assembly |
| `dmem_seed.mem` | You, optional | Initial DMEM: hex words. `@<word index>` moves on |
| `ddr_seed.mem` | You, optional | Initial DDR: `<byte address> <word>` pairs, in hex |
| `program.mem` | `rtl generate` | The machine code |
| `regfile_c<lane>.mem` | `rtl generate` | Expected registers of one lane |
| `data.mem` | `rtl generate` | Expected DMEM |
| `ddr.mem` | `rtl generate` | Expected DDR words and write bursts, if the case uses DDR |
| `perf.mem` | `rtl generate` | Expected counts for the performance counters |

A program ends with the halt `ecall`: service 0 in `a7`. A case must not fault.
Without the DDR backend (`architecture.ddr_enable: false`), the benches skip the cases
that have a `ddr.mem`.

## The GPU model

`tools/tests/gpgpu_model.py` runs the same machine code as the RTL, one instruction at
a time, and gives the expected results. It follows the rules of the hardware:

- The lanes run in lockstep, and branch with lane 0.
- Accesses decode as in `MemorySubsystemPkg::decode_access`.
- Stores of one instruction to the same DMEM byte take effect in lane order.
- A DDR store or load makes one AXI burst per group of addresses.

It reports what has no defined result: a branch that the lanes disagree on, and lanes
that store different values to one DDR word in one instruction.

Every constant of the model comes from the RTL packages. `rtl constants` reads them
with pyslang and writes `<paths.build.root>/tests/rtl/rtl_constants.txt`.

## The suites in detail

### e2e

The bench touches the GPU only through AXI4-Lite and the interrupt pin, as the host
does. It first checks the register map, the error responses and the fault reports.
Then, for each case, it clears DMEM, loads and verifies IMEM, enables the interrupt,
starts the kernel, waits for the interrupt, and compares all of DMEM with the expected
file. For a case with DDR it also compares the contents of DDR and the number of
bursts. The host cannot see the registers of the lanes, so only `smx` checks them.

### ddr

The bench uses the same top, built with `DDR_ENABLE=1`. Directed kernels store to the
framebuffers, or load seeded words and store what they read. Others get an AXI error,
and the bench checks the fault report. It reads memory through the back door of the
DDR model. Then it runs every directed case.

## Configuration

The settings are under `tests.rtl` in `config/profiles/default.yaml`.

| Option | What it does |
| --- | --- |
| `<suite>.testbench`, `<suite>.top` | The bench file and its top module |
| `<suite>.exclude_sources` | RTL directories or files that the suite leaves out |
| `<suite>.parameters` | HDL parameters, for this suite only |
| `<suite>.plusargs` | Run settings of the bench. `e2e` and `ddr` have no defaults of their own |
| `axi_slave.source`, `axi_slave.parameters` | The DDR model of every bench: latency, how often it is ready, and its seed |
| `trace.*` | Waveforms |
| `range` | The directed cases to run: `"all"`, or a range such as `"1-10"` |
| `random.*` | The number of random programs, and the seed (0 picks one) |

Each suite compiles the RTL files that `hardware.sources` describes, minus its
`exclude_sources`. The packages and interfaces in `hardware.sources.ordered` come
first. A change in a source, a header, the compiler, its options or the number of
lanes rebuilds the bench.
