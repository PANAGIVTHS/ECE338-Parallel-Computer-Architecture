"""FPGA execution adapter for the nbody program.

This adapter targets the refactored software/programs/fpga_run.py API.

The runner is generic and only knows how to:
  - load IMEM
  - write GPGPU_ARGS when they change
  - run one kernel call
  - dump the DMEM window requested by this adapter
  - pass the dumped words back to this adapter

nbody-specific ABI
------------------

GPGPU_ARGS:

    GPGPU_ARGS[0] = steps per kernel call
    GPGPU_ARGS[1] = reset, 1 only for call_index == 0

The state is the kernel's shared-memory array nbody_state (GPGPU_SHARED, in
DMEM; its address comes from nbody_layout.json), zeroed at program load:

    pos_x[32] at nbody_state + 0 words
    pos_y[32] at nbody_state + 32 words
    vel_x[32] at nbody_state + 64 words
    vel_y[32] at nbody_state + 96 words

The adapter dumps only pos_x + pos_y:

    pos_x[0..31]
    pos_y[0..31]

and writes a wide CSV row:

    step,x0,y0,x1,y1,...,x31,y31
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from fpga_run import DmemWindow, ProgramAdapter as BaseProgramAdapter


NUM_BODIES = 32

STATE_WORDS = NUM_BODIES * 4       # pos_x, pos_y, vel_x, vel_y
POSITION_OUTPUT_WORDS = NUM_BODIES * 2


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
    def __init__(self, program_dir: Path, artifact_dir: Path):
        super().__init__(program_dir, artifact_dir)

        self.csv_path = self.artifact_dir / "data.csv"
        self.current_step = 0
        self.history: list[list[int]] = []

        # These are set in configure(), from the CLI and the program's layout.
        self.steps_per_call = 1
        self.data_base_bytes = 0

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        group = parser.add_argument_group("nbody FPGA options")

        group.add_argument(
            "--steps",
            type=int,
            default=1,
            help="Logical nbody simulation steps executed by each kernel call",
        )

    def configure(
        self,
        *,
        kernel_calls: int,
        visualize: bool,
        adapter_args: argparse.Namespace,
    ) -> None:
        if adapter_args.steps < 1:
            raise SystemExit("--steps must be >= 1")

        self.steps_per_call = adapter_args.steps
        # nbody_state (GPGPU_SHARED): zeroed at program load, set by reset.
        self.data_base_bytes = self.symbol("nbody_state")

        self.current_step = 0
        self.history.clear()

        header = ["step"]
        for body in range(NUM_BODIES):
            header.extend([f"x{body}", f"y{body}"])

        with self.csv_path.open("w", newline="") as f:
            csv.writer(f).writerow(header)

        print(
            f"[INFO] nbody adapter: kernel_calls={kernel_calls}, "
            f"steps/call={self.steps_per_call}, "
            f"data_base=0x{self.data_base_bytes:08x}"
        )

    def kernel_arguments(
        self,
        *,
        call_index: int,
        adapter_args: argparse.Namespace,
    ):
        reset = 1 if call_index == 0 else 0

        return [
            self.steps_per_call,      # GPGPU_ARGS[0]: steps per kernel call
            reset,                    # GPGPU_ARGS[1]: reset on first call only
        ]

    def output_window(
        self,
        *,
        call_index: int,
        kernel_args: list[str],
        adapter_args: argparse.Namespace,
    ) -> DmemWindow:
        # Dump pos_x[32] + pos_y[32].
        return DmemWindow(
            byte_address=self.data_base_bytes,
            word_count=POSITION_OUTPUT_WORDS,
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
        self.current_step += self.steps_per_call
        row = [self.current_step]

        pos_x_word = self.data_base_bytes // 4
        pos_y_word = pos_x_word + NUM_BODIES

        for body in range(NUM_BODIES):
            x_addr = pos_x_word + body
            y_addr = pos_y_word + body

            if x_addr not in words or y_addr not in words:
                raise RuntimeError(
                    f"Missing nbody output words for body {body}: "
                    f"DMEM[{x_addr}], DMEM[{y_addr}]"
                )

            row.append(int32_from_hex(words[x_addr]))
            row.append(int32_from_hex(words[y_addr]))

        with self.csv_path.open("a", newline="") as f:
            csv.writer(f).writerow(row)

        self.history.append(row)

        print(f"[INFO] Appended nbody output row for step {row[0]} to {self.csv_path}")

    def finalize(self, *, visualize: bool, adapter_args: argparse.Namespace) -> None:
        super().finalize(visualize=visualize, adapter_args=adapter_args)
