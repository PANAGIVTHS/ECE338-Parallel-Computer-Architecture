"""FPGA execution adapter for the 3D nbody program.

This adapter targets the refactored programs/fpga_run.py API.

The runner is generic and only knows how to:
  - load IMEM
  - write GPGPU_ARGS when they change
  - run one kernel call
  - dump the DMEM window requested by this adapter
  - pass the dumped words back to this adapter

nbody-3d-specific ABI
---------------------

GPGPU_ARGS / DMEM[16..19]:

    GPGPU_ARGS[0] = base pointer, byte address, default 0x00001000
    GPGPU_ARGS[1] = steps per kernel call
    GPGPU_ARGS[2] = reset, 1 only for call_index == 0
    GPGPU_ARGS[3] = reserved, 0

The C kernel can interpret GPGPU_ARGS[0] like this:

    volatile int *base  = (volatile int *)GPGPU_ARGS[0];

    volatile int *pos_x = base;
    volatile int *pos_y = base + CORES;
    volatile int *pos_z = base + 2 * CORES;

    volatile int *vel_x = base + 3 * CORES;
    volatile int *vel_y = base + 4 * CORES;
    volatile int *vel_z = base + 5 * CORES;

Default data-region layout:

    pos_x[32] at base + 0 words
    pos_y[32] at base + 32 words
    pos_z[32] at base + 64 words
    vel_x[32] at base + 96 words
    vel_y[32] at base + 128 words
    vel_z[32] at base + 160 words

The adapter dumps only pos_x + pos_y + pos_z:

    pos_x[0..31]
    pos_y[0..31]
    pos_z[0..31]

and writes a wide CSV row:

    step,x0,y0,z0,x1,y1,z1,...,x31,y31,z31
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from pathlib import Path

from fpga_run import DmemWindow, ProgramAdapter as BaseProgramAdapter


NUM_BODIES = 32

DEFAULT_DATA_BASE_BYTES = 0x00001000
DEFAULT_DATA_LIMIT_BYTES = 0x00001800

STATE_WORDS = NUM_BODIES * 6          # pos_x,pos_y,pos_z,vel_x,vel_y,vel_z
POSITION_OUTPUT_WORDS = NUM_BODIES * 3 # pos_x,pos_y,pos_z


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
        self.current_step = 0
        self.history: list[list[int]] = []

        # These are set from adapter CLI options in configure().
        self.steps_per_call = 1
        self.data_base_bytes = DEFAULT_DATA_BASE_BYTES
        self.data_limit_bytes = DEFAULT_DATA_LIMIT_BYTES
        self.clear_state = True
        self.clear_words = STATE_WORDS

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        group = parser.add_argument_group("nbody-3d FPGA options")

        group.add_argument(
            "--steps",
            type=int,
            default=1,
            help="Logical nbody-3d simulation steps executed by each kernel call",
        )
        group.add_argument(
            "--data-base",
            type=parse_int_auto,
            default=DEFAULT_DATA_BASE_BYTES,
            help="Byte address passed to the kernel as the base pointer, default: 0x1000",
        )
        group.add_argument(
            "--data-limit",
            type=parse_int_auto,
            default=DEFAULT_DATA_LIMIT_BYTES,
            help="End byte address of the usable data region, default: 0x1800",
        )
        group.add_argument(
            "--clear-words",
            type=int,
            default=STATE_WORDS,
            help=(
                "Number of words to clear at --data-base before the first kernel call. "
                "Default clears pos_x,pos_y,pos_z,vel_x,vel_y,vel_z."
            ),
        )
        group.add_argument(
            "--no-clear-state",
            action="store_true",
            help="Do not clear the nbody-3d state region before the first kernel call",
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
        if adapter_args.data_base % 4 != 0:
            raise SystemExit("--data-base must be 4-byte aligned")
        if adapter_args.data_limit % 4 != 0:
            raise SystemExit("--data-limit must be 4-byte aligned")
        if adapter_args.data_limit <= adapter_args.data_base:
            raise SystemExit("--data-limit must be greater than --data-base")
        if adapter_args.clear_words < 0:
            raise SystemExit("--clear-words must be >= 0")

        required_words = STATE_WORDS
        available_words = (adapter_args.data_limit - adapter_args.data_base) // 4

        if available_words < required_words:
            raise SystemExit(
                f"nbody-3d needs at least {required_words} words at --data-base "
                f"for pos_x,pos_y,pos_z,vel_x,vel_y,vel_z, but only {available_words} are available"
            )

        if adapter_args.clear_words > available_words:
            raise SystemExit(
                f"--clear-words={adapter_args.clear_words} exceeds available data words {available_words}"
            )

        self.steps_per_call = adapter_args.steps
        self.data_base_bytes = adapter_args.data_base
        self.data_limit_bytes = adapter_args.data_limit
        self.clear_state = not adapter_args.no_clear_state
        self.clear_words = adapter_args.clear_words

        self.current_step = 0
        self.history.clear()

        header = ["step"]
        for body in range(NUM_BODIES):
            header.extend([f"x{body}", f"y{body}", f"z{body}"])

        with self.csv_path.open("w", newline="") as f:
            csv.writer(f).writerow(header)

        print(
            f"[INFO] nbody-3d adapter: kernel_calls={kernel_calls}, "
            f"steps/call={self.steps_per_call}, "
            f"data_base=0x{self.data_base_bytes:08x}"
        )

    def initial_dmem(self):
        """Clear nbody-3d state memory once before the kernel-call loop.

        The default clears only the nbody-3d state region:
          pos_x[32], pos_y[32], pos_z[32], vel_x[32], vel_y[32], vel_z[32]

        This is safer than clearing the whole compiler-owned data region, because
        future programs may rely on .data/.rodata contents.
        """
        if not self.clear_state or self.clear_words == 0:
            return None

        return (
            self.data_base_bytes // 4,
            [u32_hex(0)] * self.clear_words,
        )

    def kernel_arguments(
        self,
        *,
        call_index: int,
        adapter_args: argparse.Namespace,
    ):
        reset = 1 if call_index == 0 else 0

        return [
            self.data_base_bytes,     # GPGPU_ARGS[0]: byte pointer to nbody-3d state/output arrays
            self.steps_per_call,      # GPGPU_ARGS[1]: steps per kernel call
            reset,                    # GPGPU_ARGS[2]: reset on first call only
            0,                        # GPGPU_ARGS[3]: reserved
        ]

    def output_window(
        self,
        *,
        call_index: int,
        kernel_args: list[str],
        adapter_args: argparse.Namespace,
    ) -> DmemWindow:
        # Dump pos_x[32] + pos_y[32] + pos_z[32].
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
        pos_z_word = pos_y_word + NUM_BODIES

        for body in range(NUM_BODIES):
            x_addr = pos_x_word + body
            y_addr = pos_y_word + body
            z_addr = pos_z_word + body

            if x_addr not in words or y_addr not in words or z_addr not in words:
                raise RuntimeError(
                    f"Missing nbody-3d output words for body {body}: "
                    f"DMEM[{x_addr}], DMEM[{y_addr}], DMEM[{z_addr}]"
                )

            row.append(int32_from_hex(words[x_addr]))
            row.append(int32_from_hex(words[y_addr]))
            row.append(int32_from_hex(words[z_addr]))

        with self.csv_path.open("a", newline="") as f:
            csv.writer(f).writerow(row)

        self.history.append(row)

        print(f"[INFO] Appended nbody-3d output row for step {row[0]} to {self.csv_path}")

    def finalize(self, *, visualize: bool, adapter_args: argparse.Namespace) -> None:
        if not visualize:
            return

        visualize_script = self.program_dir / "visualize.py"
        if not visualize_script.exists():
            print("[INFO] No visualize.py found; skipping visualization")
            return

        print(f"[INFO] Running visualization: {visualize_script}")
        subprocess.run([sys.executable, str(visualize_script)], cwd=self.program_dir, check=True)
