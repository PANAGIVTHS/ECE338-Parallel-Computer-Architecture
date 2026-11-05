# Parameterized multiplier regression

`GPGPU.MUL_LATENCY` is the top-level configuration (default **3**, supported values
**1 or greater**). It is passed through `StreamingMultiprocessor` to every
`StreamingProcessor` and the shared `HazardUnit`. Standalone SM/SP instances can
also set their `MUL_LATENCY` parameter directly.

`Multiplier.LATENCY` counts registered stages **after EX**, not EX itself and not
the subsequent EXMEM/MEMWB registers. The arithmetic and `mul_stage_t` arrays
advance on the same edge with the same enable. Synchronous active-low reset takes
priority over global stall and clears every stage. Products retain the original
`word_t` truncation, including on invalid cycles. The initiation interval is one
unstalled cycle, independent of latency.

A replacement DSP/IP implementation must provide the same latency, initiation
interval, global clock-enable/freeze behavior, and reset behavior. Merely matching
its nominal latency is insufficient. Only the arithmetic implementation inside
`Multiplier` should need replacement; its metadata and hazard interface remain.

The hazard array contains only registered stages. EX remains a separate check.
Non-MUL issue blocking, the independent-MUL exception, the original EX-destination
comparison, load-use priority, and branch flush priority are preserved. `x0`
validity is still determined in `StreamingProcessor`; the multiplier transports
metadata without reinterpreting it. Branch feedback remains in `sp_feedback_t`;
MUL hazards use a separate parameterized port, and shared control still uses core 0.

## Run

From the repository root, with Verilator, a C++ compiler, and make installed:

```sh
python3 tests/hardware/rtl/multiplier/run.py
```

Defaults: latencies **1, 2, 3, 5**, **4 cores**, artifacts under
`build/tests/multiplier`. Override tools using `--verilator`, `--cxx`, `--make`,
core count using `--cores`, and output location using `--build-dir`.
The runner uses the existing package order and RTL source discovery, and generates
case images/traces in the build directory, not in the source test cases.
Existing Vivado builds use the explicit production manifest, which includes
`sp/Multiplier.sv`.

The unit bench checks result/rd/PC/valid alignment and every hazard stage, continuous
valid input, bubbles, overflow/sign-bit patterns, random stalls and resets, reset
while stalled, ordinary ALU operations and zero detection, and directed/random
hazard-policy cases. The integration run uses every existing SMX directed case
plus `program.asm`, covering independent/dependent products, ordinary instructions,
`x0`, forwarding, stores, loads, and crossbar stalls.

To additionally compare against a separately preserved **pre-refactor**
`hardware/rtl/gpgpu` directory:

```sh
python3 tests/hardware/rtl/multiplier/run.py --baseline-rtl /path/to/original/gpgpu
```

At latency 3, this requires byte-identical per-cycle SM controls, IDEX,
EXMEM/MEMWB, forwarded operands, writeback data, core memory requests/read data,
all core registers, and the existing per-test PC traces. The original sources
are not copied into this directory. Build warnings remain visible in `build.log`;
assertions and subprocess failures terminate the runner. `results.json` records
only completed checks. This is simulation validation, not a Vivado synthesis or
timing-closure claim. The separate E2E suite is already deferred by the project
because its bench has not been migrated to the current interface.

## Intentionally unchanged

The existing MUL/DIV detection treats every R-type instruction with
`FUNCT7_MULDIV` as multiplication, as already noted in the RTL. The existing
hazard exception also compares ID sources against `i_idex_rd` unconditionally,
even when only registered MUL stages are pending. Neither behavior is changed.

## Executed validation

Verified with Verilator 5.032 and GCC 14.2:

- Unit benches passed at latencies 1, 2, 3, and 5.
- All 25 existing SMX cases plus the added directed case passed at each latency,
  with both 4 and 32 cores.
- At latency 3, original-versus-refactored state and per-case PC traces were
  byte-identical at both core counts, including EXMEM/MEMWB and register state.
- Full-system builds emitted the same 28 warnings as the original RTL, with no
  additional warning messages after normalizing source paths and line numbers.
- Existing packaging/header Python checks: 53 passed, 3 failed. The same three
  failures reproduced against an isolated original-RTL/manifest snapshot: two
  stale assertions expect 20 production files (the original has 25 including
  memory; the refactor has 26), and the `header_not_sibling` mutation expects a
  rejection for relocating `HazardUnit`, which does not consume the header.
  Those unrelated checks were not modified.

Results and logs are under `build/tests/multiplier` (4 cores) and
`build/tests/multiplier_32` (32 cores). No Vivado synthesis or implementation was
run because Vivado is unavailable. The project already defers its separate E2E
suite; these results cover the executable SMX suite, not that deferred suite.
