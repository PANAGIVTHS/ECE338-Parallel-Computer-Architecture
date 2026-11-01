# ECALL termination regression

## Run

Requires Verilator, GNU make/C++, Python 3, and `riscv64-unknown-elf-{gcc,objdump,objcopy}`
on `PATH` (`CROSS_PREFIX` overrides the RISC-V prefix):

```sh
python tests/hardware/rtl/ecall/run.py --cores 4 32
```

This standalone runner reads the existing ordered RTL source manifest and does
not require Git metadata. Normal CLI SMX/AXI tasks continue to work in a Git
checkout. Outputs stay in `build/tests/ecall-current/`; source cases are copied
before assembly, expected-memory generation, or simulation. Options include
`--skip-directed`, `--random-iterations N` (default 25), and `--build-root PATH`.
Use a dedicated disposable build directory: the runner replaces its `cases/`.

On this host the toolchains can be activated with:

```sh
. /opt/hermes-tools/rtl-toolchain/env.sh
. /opt/hermes-tools/riscv-toolchain/env.sh
```

## Contract and implementation

- Only the exact ECALL word `00000073` is recognized. EBREAK, CSR instructions,
  and malformed SYSTEM words do not become ECALL and cannot write registers.
- ECALL's implicit `a7`/`x17` source is decoded as `rs1`, using the existing
  synchronous register read, EX/MEM and MEM/WB forwarding, and load/multiply
  interlocks. `a7` is not fixed or reserved in the compiler/register file.
- In today's single lockstep warp, service 0 in every participating lane
  requests exit. Unsupported or mixed service values are non-terminating no-ops;
  no new exception/error interface is introduced.
- The resident warp transitions RUNNING -> DRAINING -> FINISHED. Acceptance
  blocks further fetch/issue and bubbles the younger decode instruction, without
  freezing older work. All lanes' writeback, memory instructions, and multiply
  metadata must drain before `o_kernel_complete` asserts. A memory grant is not
  completion: the existing memory response handshake must finish.
- The existing host controller, CSR map, status and interrupt path are unchanged.
  RET/JALR no longer carry completion metadata. Exit state belongs to the warp,
  rather than a lane-0 return. Future divergence needs a participating-lane mask;
  future resident warps need per-warp copies and last-warp completion aggregation.
- `GPGPU_START` calls the kernel normally, then executes `li a7, 0; ecall`.
  RET/ECALL never delimit linked program images. This includes the legacy UART
  `trim_program_at_ret` helper, now a full-image compatibility normalizer.

## Coverage and observed results

Fresh runs on the supplied source tree passed at **both 4 and 32 lanes**:

| Suite | Cases per configuration |
| --- | ---: |
| Dedicated host-MMIO ECALL checks | 20 |
| Directed SMX full-register/DMEM comparisons | 29 |
| Directed AXI4-Lite DMEM/status/IRQ checks | 29 |
| Seeded randomized SMX kernels (base seed 4242) | 25 |

The dedicated bench covers exact decode; ordinary `a7` use; zero/nonzero
selectors from ALU (several forwarding distances), load and multiply; mixed lane
services; an unsupported-only program that remains running until host STOP;
older contending lane stores; younger register/store poison; wrong-path ECALL
behind a stalled redirect; nested ordinary returns with code after ECALL;
pending-exit `i_enable` disable/re-enable and reset while disabled; and repeated START launches without an
external reset. It asserts no fetch after acceptance and no completion while
pipeline or memory work remains.

The compiled `kernel.c` fixture makes nested ILP32 calls with stack saves,
returns normally through the runtime wrapper, and writes `lane_id + 105` to
DMEM. The runner inspects the real disassembly and simulates the linked image.
Volatile function-pointer calls deliberately avoid GCC's non-relaxed AUIPC
call sequence: AUIPC is outside this existing core's subset and is not added by
this change. Compiler ABI/optimization flags remain the normal program flags.

Two isolated negative mutations were also exercised: accepting every ECALL
service and reinstating RET-as-exit. Both fail the expected continuation-register
assertions. See `build/tests/ecall-current/negative_checks.json` and the referenced
negative simulation logs. The actual working RTL is never mutated by these checks.

Production-top Verilator lint succeeds with the same **36 existing warning
headers** as the untouched snapshot and no introduced warnings. The comparison
is in `build/tests/ecall-current/lint_comparison.json`.

Python coverage is in `tools/gpgpu_tasks/tests/test_ecall_tools.py` and
`test_programs.py`, plus the existing RTL task/random/native-bench tests. The
native-bench EOF check accepts `SMX_BINARY` and `SMX_TEST_ROOT`, e.g.:

```sh
export SMX_BINARY="$PWD/build/tests/ecall-current/directed_32/sim"
export SMX_TEST_ROOT="$PWD/build/tests/ecall-current"
PYTHONPATH="$PWD:$PWD/tools/gpgpu_tasks:$PWD/tools/gpgpu_cli" \
uv run --no-project --with 'pytest>=8,<9' --with 'doit>=0.37,<1' \
  --with 'pyslang>=12.1,<13' --with 'rich>=13,<15' --with pyyaml \
  python -m pytest -q \
  tools/gpgpu_tasks/tests/test_ecall_tools.py \
  tools/gpgpu_tasks/tests/test_programs.py \
  tools/gpgpu_tasks/tests/test_program_adapters.py \
  tools/gpgpu_tasks/tests/test_rtl_tasks.py \
  tools/gpgpu_tasks/tests/test_smx_native.py \
  tools/gpgpu_tasks/tests/test_smx_verilator.py \
  tools/gpgpu_tasks/tests/test_rtl_range.py \
  tools/gpgpu_tasks/tests/test_random_tester.py
```

## Limits and pre-existing failures

This is executed RTL simulation and cross-compilation, **not** Vivado synthesis,
implementation/timing closure, or an FPGA/physical-UART run. The current concrete
memory backend is BRAM (`DDR_ENABLE=0`); no future posted-write backend or SIMT
features are claimed to be tested.

The broader `test_fpga_uart_protocol.py` suite has two failures reproduced
against an untouched source snapshot with the same environment:

- `test_fpga_task_discovery_does_not_require_repo_on_pythonpath`: its subprocess
  strips `PYTHONPATH` and cannot import the uninstalled `config` package.
- `test_run_rechecks_imem_to_prevent_cross_session_program_mixup`: its mock uses
  obsolete `busy`/`done` status fields instead of required `stopped`/`faulted`,
  so it fails the status guard before the intended IMEM assertion.

Those unrelated tests/interfaces were not changed. Baseline output is retained
in `build/tests/ecall-current/baseline_uart_tests.log`.
