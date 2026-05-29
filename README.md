# ECE338-Parallel-Computer-Architecture

## Running programs on FPGA

The repository has a generic flow for compiling a program, loading it on the FPGA through UART, running it in chunks, dumping a program-defined output window, and optionally visualizing the results.  The root entry point is `./run.sh`; the program-specific behavior lives under `programs/<program>/`.

### Quick example

```bash
./run.sh -p nbody --fpga --port /dev/ttyACM0 --steps 50 --runs 10 --visualize
```

This command means:

- build the `nbody` program,
- load its RISC-V instruction memory image into the FPGA,
- run 10 kernel launches,
- ask each launch to advance 50 logical nbody steps,
- after each launch, dump the nbody output window from DMEM,
- let `programs/nbody/fpga.py` append the output to `programs/nbody/data.csv` and update the live visualization,
- after the loop, run the normal visualization script if requested.

Use the serial port that corresponds to your board, for example `/dev/ttyUSB1` or `/dev/ttyACM0`.

### Top-level wrapper: `run.sh`

The root `run.sh` is only a thin wrapper:

```bash
./run.sh ...
```

internally executes:

```bash
programs/run.sh ...
```

This exists so users can start from the repository root while keeping all program build/run logic inside `programs/`.

### Program runner: `programs/run.sh`

`programs/run.sh` performs these steps:

1. Discovers available program directories under `programs/`.
2. Parses command-line options such as:
   - `-p, --program PROGRAM`
   - `--fpga`
   - `--port PORT`
   - `--baud BAUD`
   - `--steps N`
   - `--runs N`
   - `--total-steps N`
   - `--skip-load-imem`
   - `--visualize` / `--no-visualize`
3. Builds the selected program with:

   ```bash
   make -C programs PROG=<program> clean
   make -C programs PROG=<program> <target>
   ```

   For an FPGA run it also ensures the raw instruction memory file exists:

   ```bash
   programs/<program>/<program>_instructions.mem
   ```

4. If `--fpga` was requested, it calls the generic Python FPGA runner:

   ```bash
   python3 programs/fpga_run.py \
       --program <program> \
       --port <port> \
       --baud <baud> \
       --steps-per-run <steps> \
       --runs <runs>
   ```

The shell script does not know the nbody memory layout.  It only builds the program and forwards FPGA-run options to `programs/fpga_run.py`.

### Generic FPGA loop: `programs/fpga_run.py`

`programs/fpga_run.py` owns the common UART lifecycle.  It imports one program-specific adapter from:

```text
programs/<program>/fpga.py
```

The adapter must define:

```python
class ProgramAdapter:
    ...
```

The generic flow is:

1. Import `programs/<program>/fpga.py` and construct `ProgramAdapter(program_dir=...)`.
2. Determine the IMEM file.  By default this is:

   ```text
   programs/<program>/<program>_instructions.mem
   ```

3. Ask the adapter where the output lives in DMEM:

   ```python
   output_offset_words()
   output_word_count()
   ```

4. Call the adapter's optional configuration hook:

   ```python
   configure(steps_per_run=..., runs=..., total_steps=..., visualize=...)
   ```

5. Open the UART monitor using `host/baremetal/gpgpu_uart.py`.
6. Unless `--skip-load-imem` is used, load the program into IMEM.
7. Optionally call:

   ```python
   initial_dmem()
   ```

   if the adapter provides it.
8. For each run/chunk:
   1. Compute:

      ```text
      start_step = run_index * steps_per_run
      steps_this_run = steps_per_run
      ```

      If `--total-steps` was used, the last chunk may be shorter.

   2. Call the adapter before launching the kernel:

      ```python
      before_run(run_index=..., start_step=..., steps=...)
      ```

      The adapter returns DMEM writes as either:

      ```python
      (offset_word, [word0, word1, ...])
      ```

      or a list of such tuples.  The generic runner writes those words to DMEM through UART.

   3. Start the FPGA core:

      ```python
      uart.run()
      ```

   4. Dump the adapter-defined output window:

      ```python
      output = uart.dump_dmem_bin(count=output_words, offset=output_offset)
      ```

   5. Hand the dumped words back to the adapter:

      ```python
      process_output(run_index=..., start_step=..., steps=..., words=output)
      ```

   6. Tell the host controller the read/dump phase is done, returning the core to loading state:

      ```python
      uart.done()
      ```

   7. Optionally call:

      ```python
      after_run(run_index=..., start_step=..., steps=..., words=output)
      ```

9. After all chunks finish, call:

   ```python
   finalize(visualize=...)
   ```

10. Print success.

The key idea is that `fpga_run.py` is program-agnostic.  It knows how to talk to the board, but not what a program's arguments or output mean.

### Program-specific adapter: `programs/nbody/fpga.py`

`programs/nbody/fpga.py` defines the nbody host-side ABI.  It must match the DMEM constants used by `programs/nbody/nbody.c`.

Current nbody host-visible words:

```text
DMEM[16] = magic word 0x4e424459 ("NBDY")
DMEM[17] = steps to run in this kernel launch
DMEM[18] = reset flag; 1 for first launch, 0 for later launches
DMEM[19] = logical start step
```

Current nbody output window:

```text
DMEM[1024 .. 1024 + 64)
```

There are 32 bodies.  Each body writes two output words:

```text
DMEM[1024 + body*2 + 0] = x pixel
DMEM[1024 + body*2 + 1] = y pixel
```

The nbody adapter implements the generic hooks as follows:

- `configure(...)`
  - creates or truncates `programs/nbody/data.csv`,
  - writes the CSV header,
  - clears in-memory visualization history.

- `output_offset_words()`
  - returns `1024`.

- `output_word_count()`
  - returns `NUM_BODIES * 2`, currently `64`.

- `before_run(run_index, start_step, steps)`
  - returns a write to `DMEM[16..19]`,
  - sets the reset flag to `1` only for `run_index == 0`,
  - sets reset to `0` for later chunks so the kernel continues from DMEM-resident state.

- `process_output(...)`
  - reads the dumped output words,
  - converts them from 32-bit hex to signed integers,
  - appends one row to `programs/nbody/data.csv`,
  - updates `programs/nbody/fpga_latest.svg` for live preview.

- `finalize(visualize=True)`
  - runs `programs/nbody/visualize.py` after the FPGA loop if visualization was requested.

### Chunked execution model

The intended nbody FPGA usage is chunked execution:

```text
host writes args for steps 0..49
kernel runs 50 steps
host dumps output and visualizes
host sends READ_DONE
host writes args for steps 50..99
kernel runs next 50 steps from persistent DMEM state
host dumps output and visualizes
...
```

The kernel must therefore keep persistent simulation state in fixed DMEM windows, not only in registers.  The host only reads the output window and writes the small args block before each launch.

### Restarting nbody from zero

To rebuild the nbody program from scratch while preserving the FPGA flow, keep these contracts stable first:

1. Keep `programs/nbody/fpga.py` and `programs/nbody/nbody.c` in agreement on all DMEM word offsets.
2. Start with the smallest kernel that:
   - reads `DMEM[16..19]`,
   - initializes deterministic per-body state when reset is nonzero,
   - runs `steps` iterations,
   - writes `DMEM[1024..1087]`,
   - returns with the hardware completion convention.
3. Verify one kernel launch first:

   ```bash
   ./run.sh -p nbody --fpga --port /dev/ttyUSB1 --steps 1 --runs 1 --no-visualize
   ```

4. Then verify chunking/resume behavior:

   ```bash
   ./run.sh -p nbody --fpga --port /dev/ttyUSB1 --steps 50 --runs 2 --visualize
   ```

5. Only after the minimal resumable kernel works should the full pairwise-gravity nbody logic be added back.

This staged approach makes it easier to identify whether a failure comes from the host flow, DMEM ABI, kernel completion, stack/register spilling, branch divergence, or the actual nbody physics.
