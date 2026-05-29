"""FPGA execution adapter for the nbody program.

This adapter supplies the host side of the nbody resumable DMEM ABI.  The shared
framework in programs/fpga_run.py owns the UART lifecycle; this file only knows
where nbody expects arguments/output and how to turn output words into data.csv.
"""

from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path

NUM_BODIES = 32
NBODY_ARGS_MAGIC = 0x4E424459  # "NBDY"

GPU_ARGS_BASE_WORDS = 0x00000040 // 4      # 16
GPU_OUTPUT_BASE_WORDS = 0x00001000 // 4    # 1024
GPU_OUTPUT_WORDS = NUM_BODIES * 2          # 64

GPU_DATA_BASE_WORDS = 0x00001100 // 4      # 1088
GPU_DATA_LIMIT_WORDS = 0x00001800 // 4     # 1536
GPU_DATA_WORDS = GPU_DATA_LIMIT_WORDS - GPU_DATA_BASE_WORDS


def u32_hex(value: int) -> str:
    return f"{value & 0xFFFFFFFF:08x}"


def int32_from_hex(word: str) -> int:
    value = int(word, 16) & 0xFFFFFFFF
    if value & 0x80000000:
        value -= 0x100000000
    return value


class ProgramAdapter:
    def __init__(self, program_dir: Path):
        self.program_dir = Path(program_dir)
        self.csv_path = self.program_dir / "data.csv"
        self.live_svg_path = self.program_dir / "fpga_latest.svg"
        self.history: list[list[int]] = []
        self.steps_per_run = 50
        self.runs = 1

    def configure(self, *, steps_per_run: int, runs: int, total_steps: int | None, visualize: bool) -> None:
        self.steps_per_run = steps_per_run
        self.runs = runs
        header = ["step"]
        for body in range(NUM_BODIES):
            header.extend([f"x{body}", f"y{body}"])
        with self.csv_path.open("w", newline="") as f:
            csv.writer(f).writerow(header)
        self.history.clear()

    def initial_dmem(self):
        """ Clear output and data addresses. """
        return [
            (GPU_OUTPUT_BASE_WORDS, [u32_hex(0)] * GPU_OUTPUT_WORDS),
            (GPU_DATA_BASE_WORDS, [u32_hex(0)] * GPU_DATA_WORDS),
        ]

    def output_offset_words(self) -> int:
        return GPU_OUTPUT_BASE_WORDS

    def output_word_count(self) -> int:
        return GPU_OUTPUT_WORDS

    def before_run(self, *, run_index: int, start_step: int, steps: int):
        args = [
            u32_hex(NBODY_ARGS_MAGIC),          # GPGPU_ARGS[0]
            u32_hex(steps),                     # GPGPU_ARGS[1]
            u32_hex(1 if run_index == 0 else 0),# GPGPU_ARGS[2]
            u32_hex(start_step),                # GPGPU_ARGS[3]
        ]
        return (GPU_ARGS_BASE_WORDS, args) 

    def process_output(self, *, run_index: int, start_step: int, steps: int, words: dict[int, str]) -> None:
        row = [start_step + steps]
        for body in range(NUM_BODIES):
            x_addr = GPU_OUTPUT_BASE_WORDS + body * 2
            y_addr = x_addr + 1
            x = int32_from_hex(words[x_addr])
            y = int32_from_hex(words[y_addr])
            if x_addr not in words or y_addr not in words:
                raise RuntimeError(f"Missing nbody output words for body {body}: DMEM[{x_addr}], DMEM[{y_addr}]")
            row.append(int32_from_hex(words[x_addr]))
            row.append(int32_from_hex(words[y_addr]))

        with self.csv_path.open("a", newline="") as f:
            csv.writer(f).writerow(row)
        self.history.append(row)
        self.write_live_svg()

        print(f"[INFO] Appended nbody FPGA output row for step {row[0]} to {self.csv_path}")
        print(f"[INFO] Updated live SVG preview: {self.live_svg_path}")

    def write_live_svg(self) -> None:
        if not self.history:
            return

        width = 700
        height = 700
        padding = 40
        coords = []
        for row in self.history:
            for body in range(NUM_BODIES):
                coords.append((row[1 + body * 2], row[1 + body * 2 + 1]))

        min_x = min(x for x, _ in coords)
        max_x = max(x for x, _ in coords)
        min_y = min(y for _, y in coords)
        max_y = max(y for _, y in coords)
        if min_x == max_x:
            max_x = min_x + 1
        if min_y == max_y:
            max_y = min_y + 1

        def sx(x: int) -> float:
            return padding + ((x - min_x) * (width - 2 * padding) / (max_x - min_x))

        def sy(y: int) -> float:
            return height - padding - ((y - min_y) * (height - 2 * padding) / (max_y - min_y))

        colors = ["#FFD700", "#1E90FF", "#FF4500", "#32CD32", "#DA70D6", "#00CED1", "#FF69B4", "#ADFF2F"]
        latest = self.history[-1]
        parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
            '<rect width="100%" height="100%" fill="#0b0f19"/>',
            f'<text x="{padding}" y="25" fill="white" font-family="monospace" font-size="16">nbody FPGA step {latest[0]}</text>',
        ]
        for body in range(NUM_BODIES):
            color = colors[body % len(colors)]
            points = []
            for row in self.history:
                x = row[1 + body * 2]
                y = row[1 + body * 2 + 1]
                points.append(f"{sx(x):.1f},{sy(y):.1f}")
            if len(points) > 1:
                parts.append(f'<polyline points="{" ".join(points)}" fill="none" stroke="{color}" stroke-opacity="0.45" stroke-width="1.5"/>')

            x = latest[1 + body * 2]
            y = latest[1 + body * 2 + 1]
            radius = 7 if body else 13
            fill = "#000000" if body == 0 else color
            stroke = "#FFD700" if body == 0 else "#111827"
            parts.append(f'<circle cx="{sx(x):.1f}" cy="{sy(y):.1f}" r="{radius}" fill="{fill}" stroke="{stroke}" stroke-width="2"/>')

        parts.append("</svg>")
        self.live_svg_path.write_text("\n".join(parts) + "\n")

    def finalize(self, *, visualize: bool) -> None:
        if not visualize:
            return
        visualize_script = self.program_dir / "visualize.py"
        if not visualize_script.exists():
            print("[INFO] No visualize.py found; skipping visualization")
            return
        print(f"[INFO] Running visualization: {visualize_script}")
        subprocess.run([sys.executable, str(visualize_script)], cwd=self.program_dir, check=True)
