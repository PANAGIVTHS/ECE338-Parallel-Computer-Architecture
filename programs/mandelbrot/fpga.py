"""FPGA execution adapter for the Mandelbrot program.

This adapter targets the refactored programs/fpga_run.py API.

The runner is generic and only knows how to:
  - load IMEM
  - write GPGPU_ARGS when they change
  - run one kernel call
  - dump the DMEM window requested by this adapter
  - pass the dumped words back to this adapter

Mandelbrot-specific ABI
-----------------------

Because GPGPU_ARGS has only 4 words and GPGPU_ARGS[0] is now used as an output
pointer, row and scale_q are packed into one argument.

GPGPU_ARGS / DMEM[16..19]:

    GPGPU_ARGS[0] = output row pointer, byte address, default 0x00001000
    GPGPU_ARGS[1] = packed row + scale_q
                    bits [31:26] = row, 0..63
                    bits [25:0]  = scale_q
    GPGPU_ARGS[2] = center_re_q
    GPGPU_ARGS[3] = center_im_q

The C kernel can unpack it like this:

    #define MANDEL_ROW_SHIFT 26
    #define MANDEL_SCALE_MASK ((1u << MANDEL_ROW_SHIFT) - 1u)

    volatile int *output = (volatile int *)(uintptr_t)GPGPU_ARGS[0];

    unsigned int packed = (unsigned int)GPGPU_ARGS[1];
    unsigned int row = packed >> MANDEL_ROW_SHIFT;
    int scale_q = (int)(packed & MANDEL_SCALE_MASK);

    int center_re_q = GPGPU_ARGS[2];
    int center_im_q = GPGPU_ARGS[3];

Default output layout:

    output[64] at --data-base

Each kernel call computes one 64-pixel row. 64 kernel calls form one full frame.
The adapter writes CSV rows in the format expected by visualize.py:

    frame,row,p0,p1,...,p63
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from pathlib import Path

from fpga_run import DmemWindow, ProgramAdapter as BaseProgramAdapter


WIDTH = 64
HEIGHT = 64

DEFAULT_DATA_BASE_BYTES = 0x00001000
DEFAULT_DATA_LIMIT_BYTES = 0x00001800

DEFAULT_CENTER_RE_Q = -779776
DEFAULT_CENTER_IM_Q = 138240
DEFAULT_SCALE_Q = 3145728

DEFAULT_ZOOM_SHIFT = 7

ROW_SHIFT = 26
SCALE_MASK = (1 << ROW_SHIFT) - 1


def parse_int_auto(value: str) -> int:
    """Parse decimal or 0x-prefixed integers for CLI options."""
    return int(value, 0)


def u32_hex(value: int) -> str:
    return f"{value & 0xFFFFFFFF:08x}"


def int32_from_hex(word: str) -> int:
    value = int(word, 16) & 0xFFFFFFFF
    if value & 0x80000000:
        value -= 0x100000000
    return value


class ProgramAdapter(BaseProgramAdapter):
    def __init__(self, program_dir: Path):
        super().__init__(program_dir)

        self.csv_path = self.program_dir / "data.csv"

        # Set from adapter CLI options in configure().
        self.data_base_bytes = DEFAULT_DATA_BASE_BYTES
        self.data_limit_bytes = DEFAULT_DATA_LIMIT_BYTES

        self.center_re_q = DEFAULT_CENTER_RE_Q
        self.center_im_q = DEFAULT_CENTER_IM_Q
        self.initial_scale_q = DEFAULT_SCALE_Q

        self.zoom_shift = DEFAULT_ZOOM_SHIFT

        self.frames = 1
        self.scales: list[int] = []

        self.clear_output = True

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        group = parser.add_argument_group("Mandelbrot FPGA options")

        group.add_argument(
            "--frames",
            type=int,
            default=None,
            help=(
                "Number of zoom frames. If provided, --kernel-calls must equal "
                f"--frames * {HEIGHT}."
            ),
        )
        group.add_argument(
            "--data-base",
            type=parse_int_auto,
            default=DEFAULT_DATA_BASE_BYTES,
            help="Byte address passed to the kernel as output row pointer, default: 0x1000",
        )
        group.add_argument(
            "--data-limit",
            type=parse_int_auto,
            default=DEFAULT_DATA_LIMIT_BYTES,
            help="End byte address of the usable data region, default: 0x1800",
        )
        group.add_argument(
            "--center-re-q",
            type=int,
            default=DEFAULT_CENTER_RE_Q,
            help=f"Q20 real center coordinate, default: {DEFAULT_CENTER_RE_Q}",
        )
        group.add_argument(
            "--center-im-q",
            type=int,
            default=DEFAULT_CENTER_IM_Q,
            help=f"Q20 imaginary center coordinate, default: {DEFAULT_CENTER_IM_Q}",
        )
        group.add_argument(
            "--scale-q",
            type=int,
            default=DEFAULT_SCALE_Q,
            help=f"Initial Q20 viewport scale, default: {DEFAULT_SCALE_Q}",
        )
        group.add_argument(
            "--zoom-shift",
            type=int,
            default=DEFAULT_ZOOM_SHIFT,
            help=(
                "Shift used for the division-free zoom update "
                "scale_q -= max(scale_q >> zoom_shift, 1), "
                f"default: {DEFAULT_ZOOM_SHIFT}"
            ),
        )
        group.add_argument(
            "--min-scale-q",
            type=int,
            default=1,
            help="Clamp scale_q to this minimum, default: 1",
        )
        group.add_argument(
            "--no-clear-output",
            action="store_true",
            help="Do not clear the output row window before the first kernel call",
        )

    def configure(
        self,
        *,
        kernel_calls: int,
        visualize: bool,
        adapter_args: argparse.Namespace,
    ) -> None:
        if kernel_calls < 1:
            raise SystemExit("--kernel-calls must be >= 1")
        if kernel_calls % HEIGHT != 0:
            raise SystemExit(
                f"Mandelbrot needs one kernel call per row. "
                f"--kernel-calls must be a multiple of HEIGHT={HEIGHT}."
            )

        inferred_frames = kernel_calls // HEIGHT
        if adapter_args.frames is not None:
            if adapter_args.frames < 1:
                raise SystemExit("--frames must be >= 1")
            expected_calls = adapter_args.frames * HEIGHT
            if expected_calls != kernel_calls:
                raise SystemExit(
                    f"--frames {adapter_args.frames} requires --kernel-calls {expected_calls}, "
                    f"but got --kernel-calls {kernel_calls}"
                )
            self.frames = adapter_args.frames
        else:
            self.frames = inferred_frames

        if adapter_args.data_base % 4 != 0:
            raise SystemExit("--data-base must be 4-byte aligned")
        if adapter_args.data_limit % 4 != 0:
            raise SystemExit("--data-limit must be 4-byte aligned")
        if adapter_args.data_limit <= adapter_args.data_base:
            raise SystemExit("--data-limit must be greater than --data-base")

        available_words = (adapter_args.data_limit - adapter_args.data_base) // 4
        if available_words < WIDTH:
            raise SystemExit(
                f"Mandelbrot needs at least {WIDTH} output words at --data-base, "
                f"but only {available_words} are available"
            )

        if adapter_args.scale_q < 1:
            raise SystemExit("--scale-q must be >= 1")
        if adapter_args.scale_q > SCALE_MASK:
            raise SystemExit(
                f"--scale-q must fit in {ROW_SHIFT} packed bits, max {SCALE_MASK}"
            )
        if adapter_args.zoom_shift < 1:
            raise SystemExit("--zoom-shift must be >= 1")
        if adapter_args.min_scale_q < 1:
            raise SystemExit("--min-scale-q must be >= 1")
        if adapter_args.min_scale_q > SCALE_MASK:
            raise SystemExit(f"--min-scale-q must be <= {SCALE_MASK}")

        self.data_base_bytes = adapter_args.data_base
        self.data_limit_bytes = adapter_args.data_limit

        self.center_re_q = adapter_args.center_re_q
        self.center_im_q = adapter_args.center_im_q
        self.initial_scale_q = adapter_args.scale_q

        self.zoom_shift = adapter_args.zoom_shift

        self.clear_output = not adapter_args.no_clear_output

        self.scales = self.build_scales(
            frames=self.frames,
            initial_scale_q=self.initial_scale_q,
            zoom_shift=self.zoom_shift,
            min_scale_q=adapter_args.min_scale_q,
        )

        with self.csv_path.open("w", newline="") as f:
            writer = csv.writer(f)
            header = ["frame", "row"]
            header.extend(f"p{x}" for x in range(WIDTH))
            writer.writerow(header)

        print(
            f"[INFO] Mandelbrot adapter: kernel_calls={kernel_calls}, "
            f"frames={self.frames}, rows/frame={HEIGHT}, "
            f"data_base=0x{self.data_base_bytes:08x}, "
            f"center=({self.center_re_q}, {self.center_im_q}), "
            f"scale_q={self.initial_scale_q}, zoom_shift={self.zoom_shift}"
        )

    @staticmethod
    def build_scales(
        *,
        frames: int,
        initial_scale_q: int,
        zoom_shift: int,
        min_scale_q: int,
    ) -> list[int]:
        scales: list[int] = []
        scale_q = initial_scale_q

        for _ in range(frames):
            scale_q = max(min(scale_q, SCALE_MASK), min_scale_q)
            scales.append(scale_q)

            delta = scale_q >> zoom_shift
            if delta == 0:
                delta = 1

            scale_q -= delta
            if scale_q < min_scale_q:
                scale_q = min_scale_q

        return scales

    def initial_dmem(self):
        if not self.clear_output:
            return None

        return (
            self.data_base_bytes // 4,
            [u32_hex(0)] * WIDTH,
        )

    def kernel_arguments(
        self,
        *,
        call_index: int,
        adapter_args: argparse.Namespace,
    ):
        frame = call_index // HEIGHT
        row = call_index % HEIGHT

        scale_q = self.scales[frame]

        if row >= HEIGHT:
            raise RuntimeError(f"Internal error: row={row} outside 0..{HEIGHT - 1}")
        if scale_q < 0 or scale_q > SCALE_MASK:
            raise RuntimeError(f"scale_q={scale_q} does not fit packed field")

        packed = (row << ROW_SHIFT) | (scale_q & SCALE_MASK)

        return [
            self.data_base_bytes,  # GPGPU_ARGS[0]: output row pointer byte address
            packed,                # GPGPU_ARGS[1]: row + scale_q
            self.center_re_q,      # GPGPU_ARGS[2]: Q20 center real
            self.center_im_q,      # GPGPU_ARGS[3]: Q20 center imaginary
        ]

    def output_window(
        self,
        *,
        call_index: int,
        kernel_args: list[str],
        adapter_args: argparse.Namespace,
    ) -> DmemWindow:
        # Dump output[0..63] for the current row.
        return DmemWindow(
            byte_address=self.data_base_bytes,
            word_count=WIDTH,
        )

    def process_output(
        self,
        *,
        call_index: int,
        kernel_args: list[str],
        output_window: DmemWindow,
        words: dict[int, str],
        adapter_args: argparse.Namespace,
    ) -> None:
        frame = call_index // HEIGHT
        row_index = call_index % HEIGHT

        base_word = self.data_base_bytes // 4

        row = [frame, row_index]

        for x in range(WIDTH):
            addr = base_word + x

            if addr not in words:
                raise RuntimeError(f"Missing Mandelbrot output word DMEM[{addr}]")

            row.append(int32_from_hex(words[addr]))

        with self.csv_path.open("a", newline="") as f:
            csv.writer(f).writerow(row)

        if row_index == HEIGHT - 1:
            print(f"[INFO] Completed Mandelbrot frame {frame + 1}/{self.frames}")

    def finalize(self, *, visualize: bool, adapter_args: argparse.Namespace) -> None:
        if not visualize:
            return

        visualize_script = self.program_dir / "visualize.py"
        if not visualize_script.exists():
            print("[INFO] No visualize.py found; skipping visualization")
            return

        print(f"[INFO] Running visualization: {visualize_script}")
        subprocess.run([sys.executable, str(visualize_script)], cwd=self.program_dir, check=True)
