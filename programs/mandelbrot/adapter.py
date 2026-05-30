"""FPGA execution adapter for the mandelbrot program.

One kernel launch computes one 64-pixel row.
64 kernel launches compute one full 64x64 zoom frame.
"""

from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fpga_run import (  # noqa: E402
    GPU_ARGS_BASE_WORDS,
    GPU_OUTPUT_BASE_WORDS,
    ProgramAdapter as BaseProgramAdapter,
)

WIDTH = 64
HEIGHT = 64
OUTPUT_WORDS = WIDTH

# Must match mandelbrot.c.
FP_SHIFT = 13
MAX_ITER = 64

GPU_OUTPUT_WORDS = OUTPUT_WORDS            # 64

# Boundary-focused viewport near Seahorse Valley.
DEFAULT_CENTER_RE_Q = -6092   # -0.74365 * 8192
DEFAULT_CENTER_IM_Q = 1080    #  0.13184 * 8192
DEFAULT_SCALE_Q = 24576       #  3.00000 * 8192

ZOOM_NUM = 97
ZOOM_DEN = 100
MIN_SCALE_Q = 64


def u32_hex(value: int) -> str:
    return f"{value & 0xFFFFFFFF:08x}"


def u32_from_hex(word: str) -> int:
    return int(word, 16) & 0xFFFFFFFF


class ProgramAdapter(BaseProgramAdapter):
    def __init__(self, program_dir: Path):
        super().__init__(program_dir)
        self.csv_path = self.program_dir / "data.csv"
        self.latest_pgm_path = self.program_dir / "fpga_latest.pgm"

        self.runs = 1
        self.zoom_frames = 1

        self.center_re_q = DEFAULT_CENTER_RE_Q
        self.center_im_q = DEFAULT_CENTER_IM_Q
        self.initial_scale_q = DEFAULT_SCALE_Q
        self.zoom_num = ZOOM_NUM
        self.zoom_den = ZOOM_DEN

        self.current_frame_index: int | None = None
        self.current_image: list[list[int] | None] = [None for _ in range(HEIGHT)]
        self.scale_cache: dict[int, int] = {}

    def add_arguments(self, parser) -> None:
        parser.add_argument("--center-re-q", type=int, default=DEFAULT_CENTER_RE_Q, help="Mandelbrot viewport center real coordinate in fixed-point units")
        parser.add_argument("--center-im-q", type=int, default=DEFAULT_CENTER_IM_Q, help="Mandelbrot viewport center imaginary coordinate in fixed-point units")
        parser.add_argument("--scale-q", type=int, default=DEFAULT_SCALE_Q, help="Initial Mandelbrot viewport scale in fixed-point units")
        parser.add_argument("--zoom-num", type=int, default=ZOOM_NUM, help="Per-frame zoom numerator")
        parser.add_argument("--zoom-den", type=int, default=ZOOM_DEN, help="Per-frame zoom denominator")

    def configure(self, *, steps_per_run: int, runs: int, total_steps: int | None, visualize: bool, adapter_args=None) -> None:
        if adapter_args is not None:
            self.center_re_q = adapter_args.center_re_q
            self.center_im_q = adapter_args.center_im_q
            self.initial_scale_q = adapter_args.scale_q
            self.zoom_num = adapter_args.zoom_num
            self.zoom_den = adapter_args.zoom_den

        self.runs = runs
        self.zoom_frames = (runs + HEIGHT - 1) // HEIGHT

        if runs % HEIGHT != 0:
            print(
                f"[WARNING] Mandelbrot expects runs to be a multiple of {HEIGHT}. "
                f"Got runs={runs}; the last frame will be incomplete."
            )

        header = ["frame", "row"]
        header.extend(f"p{x}" for x in range(WIDTH))

        with self.csv_path.open("w", newline="") as f:
            csv.writer(f).writerow(header)

        self.current_frame_index = None
        self.current_image = [None for _ in range(HEIGHT)]
        self.scale_cache.clear()

        print(
            f"[INFO] Mandelbrot adapter configured for {runs} kernel launches "
            f"≈ {self.zoom_frames} zoom frame(s)."
        )
        print(
            f"[INFO] Viewport: center_re_q={self.center_re_q}, "
            f"center_im_q={self.center_im_q}, scale_q={self.initial_scale_q}, "
            f"zoom={self.zoom_num}/{self.zoom_den}, FP_SHIFT={FP_SHIFT}"
        )

    def initial_dmem(self):
        return [
            (GPU_OUTPUT_BASE_WORDS, [u32_hex(0)] * GPU_OUTPUT_WORDS),
        ]

    def output_offset_words(self) -> int:
        return GPU_OUTPUT_BASE_WORDS

    def output_word_count(self) -> int:
        return GPU_OUTPUT_WORDS

    def scale_for_frame(self, frame_index: int) -> int:
        if frame_index in self.scale_cache:
            return self.scale_cache[frame_index]

        scale = self.initial_scale_q
        for _ in range(frame_index):
            scale = (scale * self.zoom_num) // self.zoom_den
            if scale < MIN_SCALE_Q:
                scale = MIN_SCALE_Q

        self.scale_cache[frame_index] = scale
        return scale

    def frame_row_from_run(self, run_index: int) -> tuple[int, int]:
        frame_index = run_index // HEIGHT
        row_index = run_index % HEIGHT
        return frame_index, row_index

    def before_run(self, *, run_index: int, start_step: int, steps: int):
        frame_index, row_index = self.frame_row_from_run(run_index)
        scale_q = self.scale_for_frame(frame_index)

        args = [
            u32_hex(row_index),          # GPGPU_ARGS[0]
            u32_hex(self.center_re_q),   # GPGPU_ARGS[1]
            u32_hex(self.center_im_q),   # GPGPU_ARGS[2]
            u32_hex(scale_q),            # GPGPU_ARGS[3]
        ]

        return (GPU_ARGS_BASE_WORDS, args)

    def process_output(self, *, run_index: int, start_step: int, steps: int, words: dict[int, str]) -> None:
        frame_index, row_index = self.frame_row_from_run(run_index)

        pixels: list[int] = []
        for x in range(WIDTH):
            addr = GPU_OUTPUT_BASE_WORDS + x
            if addr not in words:
                raise RuntimeError(f"Missing Mandelbrot output word for pixel {x}: DMEM[{addr}]")
            pixels.append(u32_from_hex(words[addr]))

        with self.csv_path.open("a", newline="") as f:
            csv.writer(f).writerow([frame_index, row_index, *pixels])

        self.update_live_preview(frame_index, row_index, pixels)

        if row_index == HEIGHT - 1:
            print(
                f"[INFO] Completed Mandelbrot frame {frame_index} "
                f"(scale_q={self.scale_for_frame(frame_index)}) -> {self.csv_path}"
            )
        else:
            print(f"[INFO] Appended Mandelbrot frame={frame_index}, row={row_index}")

    def update_live_preview(self, frame_index: int, row_index: int, pixels: list[int]) -> None:
        if self.current_frame_index != frame_index:
            self.current_frame_index = frame_index
            self.current_image = [None for _ in range(HEIGHT)]

        self.current_image[row_index] = pixels

        if any(row is None for row in self.current_image):
            return

        with self.latest_pgm_path.open("wb") as f:
            f.write(f"P5\n{WIDTH} {HEIGHT}\n255\n".encode("ascii"))
            for row in self.current_image:
                assert row is not None
                for value in row:
                    gray = 0 if value >= MAX_ITER else (value * 255) // MAX_ITER
                    f.write(bytes([gray & 0xFF]))

        print(f"[INFO] Updated live Mandelbrot preview: {self.latest_pgm_path}")

    def finalize(self, *, visualize: bool) -> None:
        if not visualize:
            return

        visualize_script = self.program_dir / "visualize.py"
        if not visualize_script.exists():
            print("[INFO] No visualize.py found; skipping visualization")
            return

        print(f"[INFO] Running visualization: {visualize_script}")
        subprocess.run([sys.executable, str(visualize_script)], cwd=self.program_dir, check=True)
