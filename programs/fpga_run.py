#!/usr/bin/env python3
"""Generic FPGA/UART execution loop for programs/<program> kernels.

The program-specific logic lives in programs/<program>/adapter.py.  This file owns
only the common host flow:

1. load IMEM once
2. optionally initialize/update DMEM through the program adapter
3. run the kernel
4. dump a program-defined DMEM output window
5. let the adapter consume/visualize that output
6. send READ_DONE so the core returns to LOADING
7. repeat until the requested run count is complete
"""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
PROGRAMS_DIR = Path(__file__).resolve().parent
BAREMETAL_DIR = REPO_ROOT / "host" / "baremetal"

# Shared DMEM ABI windows used by programs/<program>/adapter.py.
GPU_ARGS_BASE_WORDS = 0x00000040 // 4      # 16
GPU_OUTPUT_BASE_WORDS = 0x00001000 // 4    # 1024

sys.path.insert(0, str(BAREMETAL_DIR))

from gpgpu_uart import GpgpuUartMonitor, read_mem_file  # noqa: E402

# When this file is executed as python programs/fpga_run.py its module name
# is __main__. Program adapters import the shared base class with
# from fpga_run import ProgramAdapter, so expose the running module under
# that import name before loading adapters. This avoids creating a second copy
# of this module and keeps isinstance/issubclass checks reliable.
sys.modules.setdefault("fpga_run", sys.modules[__name__])


class AdapterProtocolError(RuntimeError):
    pass


class ProgramAdapter:
    """Base class for program-specific FPGA/UART adapters.

    The generic runner owns the UART lifecycle. Subclasses in
    programs/<program>/adapter.py override the hooks below to describe the
    program's IMEM path, DMEM output window, optional DMEM writes, CSV/output
    conversion, and final visualization.
    """

    def __init__(self, program_dir: Path):
        self.program_dir = Path(program_dir)

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Add program-specific FPGA CLI arguments to parser."""

    def configure(
        self,
        *,
        steps_per_run: int,
        runs: int,
        total_steps: int | None,
        visualize: bool,
        adapter_args: argparse.Namespace | None = None,
    ) -> None:
        """Receive CLI-derived run settings before UART execution starts."""

    def imem_path(self) -> Path:
        """Return this program's default instruction-memory image."""
        return self.program_dir / f"{self.program_dir.name}_instructions.mem"

    def output_offset_words(self) -> int:
        """Return the DMEM word offset to dump after each kernel run."""
        raise NotImplementedError("Program adapter must define output_offset_words()")

    def output_word_count(self) -> int:
        """Return the number of DMEM words to dump after each kernel run."""
        raise NotImplementedError("Program adapter must define output_word_count()")

    def initial_dmem(self) -> Any:
        """Optional DMEM writes performed once before the run loop."""
        return None

    def before_run(self, *, run_index: int, start_step: int, steps: int) -> Any:
        """Optional DMEM writes performed immediately before each launch."""
        return None

    def process_output(
        self,
        *,
        run_index: int,
        start_step: int,
        steps: int,
        words: dict[int, str],
    ) -> None:
        """Consume dumped DMEM words for one completed kernel run."""

    def after_run(self, *, run_index: int, start_step: int, steps: int, words: dict[int, str]) -> Any:
        """Optional DMEM writes performed after READ_DONE for the run."""
        return None

    def finalize(self, *, visualize: bool) -> None:
        """Optional finalization/visualization hook after the UART loop."""


def load_adapter(program: str) -> Any:
    adapter_path = PROGRAMS_DIR / program / "adapter.py"
    if not adapter_path.exists():
        raise FileNotFoundError(
            f"{adapter_path} not found. Add a program adapter that defines ProgramAdapter."
        )

    spec = importlib.util.spec_from_file_location(f"{program}_fpga_adapter", adapter_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not import adapter from {adapter_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    adapter_cls = getattr(module, "ProgramAdapter", None)
    if adapter_cls is None:
        raise AdapterProtocolError(f"{adapter_path} must define a ProgramAdapter class")
    if not isinstance(adapter_cls, type) or not issubclass(adapter_cls, ProgramAdapter):
        raise AdapterProtocolError(
            f"{adapter_path} ProgramAdapter must inherit from fpga_run.ProgramAdapter"
        )
    return adapter_cls(program_dir=PROGRAMS_DIR / program)


def maybe_call(obj: Any, name: str, *args, default=None, **kwargs):
    fn = getattr(obj, name, None)
    if fn is None:
        return default
    return fn(*args, **kwargs)


def normalize_dmem_updates(updates: Any) -> list[tuple[int, list[int | str]]]:
    """Normalize adapter DMEM updates to [(offset, words), ...]."""
    if not updates:
        return []

    if isinstance(updates, tuple) and len(updates) == 2:
        offset, words = updates
        return [(int(offset), list(words))]

    normalized = []
    for item in updates:
        if not isinstance(item, tuple) or len(item) != 2:
            raise AdapterProtocolError(
                "DMEM updates must be (offset, words) or an iterable of those tuples"
            )
        offset, words = item
        normalized.append((int(offset), list(words)))
    return normalized


def load_dmem_updates(uart: GpgpuUartMonitor, updates: Any, *, verbose: bool = False) -> None:
    for offset, words in normalize_dmem_updates(updates):
        if verbose:
            print(f"[INFO] Loading {len(words)} DMEM words at offset {offset}")
        uart.load_dmem_bin(words, offset=offset)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a programs/<program> kernel on the FPGA over UART")
    parser.add_argument("-p", "--program", required=True, help="Program directory under programs/")
    parser.add_argument("--adapter-help", action="store_true", help="Show adapter-specific FPGA arguments for --program and exit")
    parser.add_argument("--port", default=None, help="Serial port, e.g. /dev/ttyUSB1")
    parser.add_argument("--baud", type=int, default=115200, help="UART baud rate")
    parser.add_argument("--runs", type=int, default=None, help="Number of kernel launches/chunks")
    parser.add_argument("--steps", "--steps-per-run", dest="steps_per_run", type=int, default=50, help="Logical simulation steps per kernel run")
    parser.add_argument("--total-steps", type=int, default=None, help="Alternative to --runs; rounded up by --steps-per-run")
    parser.add_argument("--imem", type=Path, default=None, help="Override IMEM .mem file path")
    parser.add_argument("--imem-offset", type=int, default=0, help="IMEM word offset for program load")
    parser.add_argument("--skip-load-imem", action="store_true", help="Do not reload IMEM before the loop")
    parser.add_argument("--output-offset", type=int, default=None, help="Override output DMEM word offset")
    parser.add_argument("--output-words", type=int, default=None, help="Override output DMEM word count")
    parser.add_argument("--no-visualize", action="store_true", help="Disable adapter visualization/finalization")
    parser.add_argument("--verbose", action="store_true", help="Print UART traffic and framework details")
    return parser


def compute_runs(args: argparse.Namespace) -> int:
    if args.runs is not None and args.total_steps is not None:
        raise SystemExit("Use either --runs or --total-steps, not both")
    if args.runs is not None:
        if args.runs < 1:
            raise SystemExit("--runs must be >= 1")
        return args.runs
    if args.total_steps is not None:
        if args.total_steps < 1:
            raise SystemExit("--total-steps must be >= 1")
        return (args.total_steps + args.steps_per_run - 1) // args.steps_per_run
    return 1


def default_imem_path(program: str) -> Path:
    return PROGRAMS_DIR / program / f"{program}_instructions.mem"


def run_visualize_py(program_dir: Path) -> None:
    script = program_dir / "visualize.py"
    if script.exists():
        subprocess.run([sys.executable, str(script)], cwd=program_dir, check=True)


def main() -> int:
    parser = build_parser()
    args, adapter_argv = parser.parse_known_args()
    if args.steps_per_run < 1:
        raise SystemExit("--steps-per-run must be >= 1")

    adapter = load_adapter(args.program)
    adapter_parser = argparse.ArgumentParser(
        prog=f"{Path(sys.argv[0]).name} -p {args.program} [adapter args]",
        description=f"Adapter-specific FPGA arguments for {args.program}",
    )
    maybe_call(adapter, "add_arguments", adapter_parser, default=None)
    if args.adapter_help:
        adapter_parser.print_help()
        return 0
    adapter_args = adapter_parser.parse_args(adapter_argv)

    if args.port is None:
        raise SystemExit("--port is required unless --adapter-help is used")

    program_dir = PROGRAMS_DIR / args.program
    runs = compute_runs(args)

    imem_path = args.imem or maybe_call(adapter, "imem_path", default=default_imem_path(args.program))
    imem_path = Path(imem_path)
    if not imem_path.is_absolute():
        imem_path = REPO_ROOT / imem_path

    output_offset = args.output_offset
    if output_offset is None:
        output_offset = maybe_call(adapter, "output_offset_words", default=None)
    output_words = args.output_words
    if output_words is None:
        output_words = maybe_call(adapter, "output_word_count", default=None)
    if output_offset is None or output_words is None:
        raise AdapterProtocolError(
            "Program adapter must provide output_offset_words() and output_word_count(), "
            "or pass --output-offset and --output-words."
        )

    maybe_call(
        adapter,
        "configure",
        steps_per_run=args.steps_per_run,
        runs=runs,
        total_steps=args.total_steps,
        visualize=not args.no_visualize,
        adapter_args=adapter_args,
    )

    print(f"[INFO] Program        : {args.program}")
    print(f"[INFO] Port           : {args.port} @ {args.baud}")
    print(f"[INFO] Runs           : {runs}")
    print(f"[INFO] Steps/run      : {args.steps_per_run}")
    print(f"[INFO] IMEM           : {imem_path}")
    print(f"[INFO] Output window  : DMEM[{output_offset}:{output_offset + output_words})")

    with GpgpuUartMonitor(args.port, args.baud, verbose=args.verbose) as uart:
        if not args.skip_load_imem:
            program_words = read_mem_file(imem_path)
            print(f"[INFO] Loading {len(program_words)} IMEM words at offset {args.imem_offset}")
            uart.load_imem_bin(program_words, offset=args.imem_offset)

        load_dmem_updates(
            uart,
            maybe_call(adapter, "initial_dmem", default=None),
            verbose=args.verbose,
        )

        for run_index in range(runs):
            start_step = run_index * args.steps_per_run
            steps_this_run = args.steps_per_run
            if args.total_steps is not None:
                steps_this_run = min(args.steps_per_run, args.total_steps - start_step)

            print(
                f"[INFO] Kernel run {run_index + 1}/{runs} "
                f"(start_step={start_step}, steps={steps_this_run})"
            )

            load_dmem_updates(
                uart,
                maybe_call(
                    adapter,
                    "before_run",
                    run_index=run_index,
                    start_step=start_step,
                    steps=steps_this_run,
                    default=None,
                ),
                verbose=args.verbose,
            )

            uart.run()
            output = uart.dump_dmem_bin(count=int(output_words), offset=int(output_offset))

            maybe_call(
                adapter,
                "process_output",
                run_index=run_index,
                start_step=start_step,
                steps=steps_this_run,
                words=output,
                default=None,
            )

            uart.done()

            load_dmem_updates(
                uart,
                maybe_call(
                    adapter,
                    "after_run",
                    run_index=run_index,
                    start_step=start_step,
                    steps=steps_this_run,
                    words=output,
                    default=None,
                ),
                verbose=args.verbose,
            )

    maybe_call(adapter, "finalize", visualize=not args.no_visualize, default=None)
    print("[SUCCESS] FPGA run loop complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
