"""FPGA execution adapter for the mandelbrot program.

This adapter matches the generic programs/fpga_run.py flow where each kernel
launch produces one output window.

Mandelbrot ABI
--------------

GPGPU_ARGS / DMEM[16..19]:

    GPGPU_ARGS[0] = row index, 0..63
    GPGPU_ARGS[1] = center_re_q, Q10 fixed-point
    GPGPU_ARGS[2] = center_im_q, Q10 fixed-point
    GPGPU_ARGS[3] = scale_q, Q10 fixed-point viewport width

GPGPU_OUTPUT / DMEM[1024..1087]:

    GPGPU_OUTPUT[0..63] = iteration counts for the selected row

One kernel launch computes one 64-pixel row. Therefore, one full 64x64
Mandelbrot frame requires 64 kernel launches.

Example:

    # 120 zoom frames * 64 rows/frame = 7680 kernel launches
    python programs/fpga_run.py -p mandelbrot --port /dev/ttyUSB1 --runs 7680
"""

from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path

WIDTH = 64
HEIGHT = 64
OUTPUT_WORDS = WIDTH

# Fixed-point format used by mandelbrot.c.
FP_SHIFT = 10
FP_ONE = 1 << FP_SHIFT
MAX_ITER = 64

# Host-visible DMEM word offsets from gpgpu.ld.
GPU_ARGS_BASE_WORDS = 0x00000040 // 4      # 16
GPU_OUTPUT_BASE_WORDS = 0x00001000 // 4    # 1024
GPU_OUTPUT_WORDS = OUTPUT_WORDS            # 64

# Default Mandelbrot viewport, matching mandelbrot.c.
DEFAULT_CENTER_RE_Q = -768   # -0.75 * 1024
DEFAULT_CENTER_IM_Q = 0
DEFAULT_SCALE_Q = 3072       #  3.00 * 1024

# Zoom factor applied once per complete 64-row frame.
# scale_q(frame + 1) = scale_q(frame) * ZOOM_NUM / ZOOM_DEN
ZOOM_NUM = 97
ZOOM_DEN = 100


def u32_hex(value: int) -> str:
    """Return value as an unsigned 32-bit hex word for DMEM loading."""
    return f"{value & 0xFFFFFFFF:08x}"


def u32_from_hex(word: str) -> int:
    return int(word, 16) & 0xFFFFFFFF


class ProgramAdapter:
    def __init__(self, program_dir: Path):
        self.program_dir = Path(program_dir)
        self.csv_path = self.program_dir / "data.csv"
        self.latest_pgm_path = self.program_dir / "fpga_latest.pgm"

        self.runs = 1
        self.zoom_frames = 1

        self.center_re_q = DEFAULT_CENTER_RE_Q
        self.center_im_q = DEFAULT_CENTER_IM_Q
        self.initial_scale_q = DEFAULT_SCALE_Q
        self.zoom_num = ZOOM_NUM
        self.zoom_den = ZOOM_DEN

        # Used only for the lightweight live preview.
        self.current_frame_index: int | None = None
        self.current_image: list[list[int] | None] = [None for _ in range(HEIGHT)]
        self.scale_cache: dict[int, int] = {}

    def configure(self, *, steps_per_run: int, runs: int, total_steps: int | None, visualize: bool) -> None:
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
            f"zoom={self.zoom_num}/{self.zoom_den}"
        )

    def initial_dmem(self):
        """Clear the output window once before the run loop."""
        return [
            (GPU_OUTPUT_BASE_WORDS, [u32_hex(0)] * GPU_OUTPUT_WORDS),
        ]

    def output_offset_words(self) -> int:
        return GPU_OUTPUT_BASE_WORDS

    def output_word_count(self) -> int:
        return GPU_OUTPUT_WORDS

    def scale_for_frame(self, frame_index: int) -> int:
        """Compute the Q10 viewport scale for a zoom frame."""
        if frame_index in self.scale_cache:
            return self.scale_cache[frame_index]

        scale = self.initial_scale_q
        for _ in range(frame_index):
            scale = (scale * self.zoom_num) // self.zoom_den
            if scale < 1:
                scale = 1

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

            # Iteration counts are non-negative and fit in u32.
            pixels.append(u32_from_hex(words[addr]))

        with self.csv_path.open("a", newline="") as f:
            csv.writer(f).writerow([frame_index, row_index, *pixels])

        self.update_live_preview(frame_index, row_index, pixels)

        if row_index == HEIGHT - 1:
            scale_q = self.scale_for_frame(frame_index)
            print(
                f"[INFO] Completed Mandelbrot frame {frame_index} "
                f"(scale_q={scale_q}) -> {self.csv_path}"
            )
        else:
            print(f"[INFO] Appended Mandelbrot frame={frame_index}, row={row_index}")

    def update_live_preview(self, frame_index: int, row_index: int, pixels: list[int]) -> None:
        """Write a tiny binary PGM preview whenever a full frame is available."""
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
                    if value >= MAX_ITER:
                        gray = 0
                    else:
                        gray = (value * 255) // MAX_ITER
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
