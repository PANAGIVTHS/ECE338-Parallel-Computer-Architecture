#!/usr/bin/env python3
"""Generic FPGA/UART execution loop for programs/<program> kernels.

The program-specific logic lives in programs/<program>/fpga.py.  This file owns
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
sys.path.insert(0, str(BAREMETAL_DIR))

from gpgpu_uart import GpgpuUartMonitor, read_mem_file  # noqa: E402


class AdapterProtocolError(RuntimeError):
    pass


def load_adapter(program: str) -> Any:
    adapter_path = PROGRAMS_DIR / program / "fpga.py"
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
    parser.add_argument("--port", required=True, help="Serial port, e.g. /dev/ttyUSB1")
    parser.add_argument("--baud", type=int, default=115200, help="UART baud rate")
    parser.add_argument("--runs", type=int, default=None, help="Number of kernel launches/chunks")
    parser.add_argument("--steps-per-run", type=int, default=50, help="Logical simulation steps per kernel run")
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
    args = build_parser().parse_args()
    if args.steps_per_run < 1:
        raise SystemExit("--steps-per-run must be >= 1")

    adapter = load_adapter(args.program)
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
