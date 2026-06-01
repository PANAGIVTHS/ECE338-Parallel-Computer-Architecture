#!/usr/bin/env python3
"""Generic FPGA/UART execution loop for programs/<program> kernels.

This runner owns only the common host-side UART flow:

1. load IMEM once
2. optionally let the adapter initialize DMEM
3. ask the adapter for the next kernel argument words
4. write GPGPU_ARGS only when those words changed
5. run the kernel once
6. ask the adapter which DMEM window to dump
7. dump that DMEM window and let the adapter process it
8. send READ_DONE so the cores return to LOADING
9. repeat for --kernel-calls launches

Program-specific logic belongs in programs/<program>/fpga.py.
"""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
PROGRAMS_DIR = Path(__file__).resolve().parent
BAREMETAL_DIR = REPO_ROOT / "host" / "baremetal"

sys.path.insert(0, str(BAREMETAL_DIR))

from gpgpu_uart import GpgpuUartMonitor, read_mem_file  # noqa: E402


# If adapters do:
#
#   from fpga_run import ProgramAdapter, DmemWindow
#
# and this file is executed as `python programs/fpga_run.py`, then its runtime
# module name is `__main__`, not `fpga_run`. This alias prevents Python from
# importing a second copy of this file.
sys.modules.setdefault("fpga_run", sys.modules[__name__])


GPU_ARGS_BASE_WORDS = 0x00000040 // 4
GPU_ARGS_WORDS = 4


class AdapterProtocolError(RuntimeError):
    """Raised when a program adapter violates the expected protocol."""


@dataclass(frozen=True)
class DmemWindow:
    """A contiguous DMEM window described by byte address and word count.

    The RISC-V core sees ordinary byte addresses. The host UART DMEM API uses
    word offsets. Therefore byte_address must be 4-byte aligned.
    """

    byte_address: int
    word_count: int

    @property
    def word_offset(self) -> int:
        if self.byte_address % 4 != 0:
            raise AdapterProtocolError(
                f"DMEM byte address 0x{self.byte_address:08x} is not 4-byte aligned"
            )
        return self.byte_address // 4


class ProgramAdapter:
    """Base class for program-specific FPGA adapters.

    Subclasses should live in programs/<program>/fpga.py and define:

        class ProgramAdapter(fpga_run.ProgramAdapter):
            ...

    Minimal methods to override:
      - kernel_arguments()
      - output_window()
      - process_output()

    Optional methods:
      - add_arguments()
      - configure()
      - imem_path()
      - initial_dmem()
      - finalize()
    """

    def __init__(self, program_dir: Path):
        self.program_dir = Path(program_dir)

    # ---------- CLI / setup ----------

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Add adapter-specific FPGA CLI options."""

    def configure(
        self,
        *,
        kernel_calls: int,
        visualize: bool,
        adapter_args: argparse.Namespace,
    ) -> None:
        """Receive CLI-derived settings before UART execution starts."""

    def imem_path(self) -> Path:
        """Return this program's default instruction-memory image."""
        return self.program_dir / f"{self.program_dir.name}_instructions.mem"

    # ---------- DMEM / run hooks ----------

    def initial_dmem(self) -> Any:
        """Optional DMEM writes performed once before the kernel-call loop.

        Return format:
          - None
          - (word_offset, words)
          - [(word_offset, words), ...]

        where words are ints or 8-hex-digit strings.
        """
        return None

    def kernel_arguments(
        self,
        *,
        call_index: int,
        adapter_args: argparse.Namespace,
    ) -> Iterable[int | str]:
        """Return the 0..4 words to write into GPGPU_ARGS.

        The runner normalizes this to exactly four words by zero-padding.
        The words are written to DMEM[16..19] only if they changed relative to
        the previous kernel call.
        """
        raise NotImplementedError("ProgramAdapter.kernel_arguments() must be overridden")

    def output_window(
        self,
        *,
        call_index: int,
        kernel_args: list[str],
        adapter_args: argparse.Namespace,
    ) -> DmemWindow:
        """Return the DMEM window to dump after this kernel call."""
        raise NotImplementedError("ProgramAdapter.output_window() must be overridden")

    def process_output(
        self,
        *,
        call_index: int,
        kernel_args: list[str],
        output_window: DmemWindow,
        words: dict[int, str],
        adapter_args: argparse.Namespace,
    ) -> None:
        """Consume one dumped output window."""

    def finalize(self, *, visualize: bool, adapter_args: argparse.Namespace) -> None:
        """Optional finalization/visualization hook after the loop."""
        if not visualize:
            return

        visualize_script = self.program_dir / "visualize.py"
        if not visualize_script.exists():
            print("[INFO] No visualize.py found; skipping visualization")
            return

        print(f"[INFO] Running visualization: {visualize_script}")
        subprocess.run([sys.executable, str(visualize_script)], cwd=self.program_dir, check=True)


def u32_hex(value: int) -> str:
    return f"{value & 0xFFFFFFFF:08x}"


def normalize_word(word: int | str) -> str:
    if isinstance(word, int):
        return u32_hex(word)

    text = str(word).strip().lower()
    if text.startswith("0x"):
        return u32_hex(int(text, 16))

    # Accept either decimal strings or raw 8-digit hex words.
    try:
        if all(ch in "0123456789abcdef" for ch in text) and len(text) <= 8:
            return f"{int(text, 16) & 0xFFFFFFFF:08x}"
        return u32_hex(int(text, 10))
    except ValueError as exc:
        raise AdapterProtocolError(f"Invalid DMEM word {word!r}") from exc


def normalize_words(words: Iterable[int | str]) -> list[str]:
    return [normalize_word(word) for word in words]


def normalize_kernel_args(args: Iterable[int | str]) -> list[str]:
    words = normalize_words(args)

    if len(words) > GPU_ARGS_WORDS:
        raise AdapterProtocolError(
            f"kernel_arguments() returned {len(words)} words, but GPGPU_ARGS has only {GPU_ARGS_WORDS}"
        )

    while len(words) < GPU_ARGS_WORDS:
        words.append("00000000")

    return words


def normalize_dmem_updates(updates: Any) -> list[tuple[int, list[str]]]:
    """Normalize adapter DMEM updates to [(word_offset, words), ...]."""
    if not updates:
        return []

    if isinstance(updates, tuple) and len(updates) == 2:
        offset, words = updates
        return [(int(offset), normalize_words(words))]

    normalized: list[tuple[int, list[str]]] = []

    for item in updates:
        if not isinstance(item, tuple) or len(item) != 2:
            raise AdapterProtocolError(
                "DMEM updates must be (word_offset, words) or an iterable of those tuples"
            )
        offset, words = item
        normalized.append((int(offset), normalize_words(words)))

    return normalized


def load_dmem_updates(
    uart: GpgpuUartMonitor,
    updates: Any,
    *,
    verbose: bool = False,
) -> None:
    for offset, words in normalize_dmem_updates(updates):
        if verbose:
            print(f"[INFO] Loading {len(words)} DMEM word(s) at offset {offset}")
        uart.load_dmem_bin(words, offset=offset)


def load_adapter(program: str) -> ProgramAdapter:
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
    if not isinstance(adapter_cls, type) or not issubclass(adapter_cls, ProgramAdapter):
        raise AdapterProtocolError(
            f"{adapter_path} ProgramAdapter must inherit from fpga_run.ProgramAdapter"
        )

    return adapter_cls(program_dir=PROGRAMS_DIR / program)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a programs/<program> kernel on the FPGA over UART"
    )

    parser.add_argument("-p", "--program", required=True, help="Program directory under programs/")
    parser.add_argument("--adapter-help", action="store_true", help="Show adapter-specific arguments and exit")
    parser.add_argument("--port", default=None, help="Serial port, e.g. /dev/ttyUSB1")
    parser.add_argument("--baud", type=int, default=115200, help="UART baud rate")
    parser.add_argument("--kernel-calls", type=int, default=1, help="Number of kernel launches")
    parser.add_argument("--imem", type=Path, default=None, help="Override IMEM .mem file path")
    parser.add_argument("--imem-offset", type=int, default=0, help="IMEM word offset for program load")
    parser.add_argument("--skip-load-imem", action="store_true", help="Do not reload IMEM before the loop")
    parser.add_argument("--args-offset", type=int, default=GPU_ARGS_BASE_WORDS, help="DMEM word offset for GPGPU_ARGS")
    parser.add_argument("--no-visualize", action="store_true", help="Disable adapter visualization/finalization")
    parser.add_argument("--verbose", action="store_true", help="Print UART traffic and framework details")

    return parser


def build_adapter_parser(program: str, adapter: ProgramAdapter) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=f"{Path(sys.argv[0]).name} -p {program} [adapter args]",
        description=f"Adapter-specific FPGA arguments for {program}",
    )
    adapter.add_arguments(parser)
    return parser


@dataclass(frozen=True)
class ParsedArgs:
    generic: argparse.Namespace
    adapter: argparse.Namespace
    program_adapter: ProgramAdapter


def parse_args(argv: list[str] | None = None) -> ParsedArgs:
    parser = build_parser()
    generic_args, adapter_argv = parser.parse_known_args(argv)

    adapter = load_adapter(generic_args.program)
    adapter_parser = build_adapter_parser(generic_args.program, adapter)

    if generic_args.adapter_help:
        adapter_parser.print_help()
        raise SystemExit(0)

    adapter_args = adapter_parser.parse_args(adapter_argv)

    if generic_args.port is None:
        raise SystemExit("--port is required unless --adapter-help is used")
    if generic_args.kernel_calls < 1:
        raise SystemExit("--kernel-calls must be >= 1")
    if generic_args.args_offset < 0:
        raise SystemExit("--args-offset must be >= 0")

    return ParsedArgs(
        generic=generic_args,
        adapter=adapter_args,
        program_adapter=adapter,
    )


def resolve_imem_path(args: argparse.Namespace, adapter: ProgramAdapter) -> Path:
    imem_path = args.imem or adapter.imem_path()
    imem_path = Path(imem_path)

    if not imem_path.is_absolute():
        imem_path = REPO_ROOT / imem_path

    return imem_path


def load_imem_once(
    *,
    uart: GpgpuUartMonitor,
    args: argparse.Namespace,
    imem_path: Path,
) -> None:
    if args.skip_load_imem:
        print("[INFO] Skipping IMEM load")
        return

    program_words = read_mem_file(imem_path)
    print(f"[INFO] Loading {len(program_words)} IMEM word(s) at offset {args.imem_offset}")
    uart.load_imem_bin(program_words, offset=args.imem_offset)


def load_kernel_args_if_changed(
    *,
    uart: GpgpuUartMonitor,
    args_offset: int,
    previous_args: list[str] | None,
    current_args: list[str],
    verbose: bool,
) -> list[str]:
    if previous_args == current_args:
        if verbose:
            print("[INFO] GPGPU_ARGS unchanged; skipping DMEM argument write")
        return previous_args

    if verbose:
        print(f"[INFO] Loading GPGPU_ARGS at DMEM[{args_offset}:{args_offset + len(current_args)})")
    uart.load_dmem_bin(current_args, offset=args_offset)
    return current_args


def run_kernel_call(
    *,
    uart: GpgpuUartMonitor,
    adapter: ProgramAdapter,
    generic_args: argparse.Namespace,
    adapter_args: argparse.Namespace,
    call_index: int,
    previous_kernel_args: list[str] | None,
) -> list[str]:
    kernel_args = normalize_kernel_args(
        adapter.kernel_arguments(call_index=call_index, adapter_args=adapter_args)
    )

    previous_kernel_args = load_kernel_args_if_changed(
        uart=uart,
        args_offset=generic_args.args_offset,
        previous_args=previous_kernel_args,
        current_args=kernel_args,
        verbose=generic_args.verbose,
    )

    print(f"[INFO] Kernel call {call_index + 1}/{generic_args.kernel_calls}")

    uart.run()

    window = adapter.output_window(
        call_index=call_index,
        kernel_args=kernel_args,
        adapter_args=adapter_args,
    )

    if window.word_count < 1:
        raise AdapterProtocolError("output_window().word_count must be >= 1")

    if generic_args.verbose:
        print(
            f"[INFO] Dumping DMEM[{window.word_offset}:{window.word_offset + window.word_count}) "
            f"from byte address 0x{window.byte_address:08x}"
        )

    output_words = uart.dump_dmem_bin(
        count=window.word_count,
        offset=window.word_offset,
    )

    adapter.process_output(
        call_index=call_index,
        kernel_args=kernel_args,
        output_window=window,
        words=output_words,
        adapter_args=adapter_args,
    )

    uart.done()

    return previous_kernel_args


def main(argv: list[str] | None = None) -> int:
    parsed = parse_args(argv)
    args = parsed.generic
    adapter_args = parsed.adapter
    adapter = parsed.program_adapter

    imem_path = resolve_imem_path(args, adapter)

    adapter.configure(
        kernel_calls=args.kernel_calls,
        visualize=not args.no_visualize,
        adapter_args=adapter_args,
    )

    print(f"[INFO] Program       : {args.program}")
    print(f"[INFO] Port          : {args.port} @ {args.baud}")
    print(f"[INFO] Kernel calls  : {args.kernel_calls}")
    print(f"[INFO] IMEM          : {imem_path}")
    print(f"[INFO] Args window   : DMEM[{args.args_offset}:{args.args_offset + GPU_ARGS_WORDS})")

    previous_kernel_args: list[str] | None = None

    with GpgpuUartMonitor(args.port, args.baud, verbose=args.verbose) as uart:
        load_imem_once(uart=uart, args=args, imem_path=imem_path)

        load_dmem_updates(
            uart,
            adapter.initial_dmem(),
            verbose=args.verbose,
        )

        for call_index in range(args.kernel_calls):
            previous_kernel_args = run_kernel_call(
                uart=uart,
                adapter=adapter,
                generic_args=args,
                adapter_args=adapter_args,
                call_index=call_index,
                previous_kernel_args=previous_kernel_args,
            )

    adapter.finalize(visualize=not args.no_visualize, adapter_args=adapter_args)

    print("[SUCCESS] FPGA run loop complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
