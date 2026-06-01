"""FPGA execution adapter for the adjacent-differences program.

This adapter targets the refactored programs/fpga_run.py API.

differences-specific ABI
------------------------

GPGPU_ARGS / DMEM[16..19]:

    GPGPU_ARGS[0] = base pointer, byte address, default 0x00001000
    GPGPU_ARGS[1] = number of output differences, default 32
    GPGPU_ARGS[2] = reserved, 0
    GPGPU_ARGS[3] = reserved, 0

Default data-region layout:

    data[33] at base + 0 words
        data[0] is padding
        data[1..32] are the logical input values

    diff[32] at base + 33 words

Expected kernel logic:

    volatile int *base = (volatile int *)(uintptr_t)GPGPU_ARGS[0];
    int n = GPGPU_ARGS[1];

    volatile int *data = base;
    volatile int *diff = base + (n + 1);

    unsigned int tid = gpgpu_thread_id();
    diff[tid] = data[tid + 1] - data[tid];

The adapter initializes data[] from the host, runs the kernel, dumps
data[] + diff[], and writes a CSV file.
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from pathlib import Path

from fpga_run import DmemWindow, ProgramAdapter as BaseProgramAdapter


DEFAULT_NUM_VALUES = 32
DEFAULT_DATA_BASE_BYTES = 0x00001000
DEFAULT_DATA_LIMIT_BYTES = 0x00001800


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

        self.num_values = DEFAULT_NUM_VALUES
        self.data_base_bytes = DEFAULT_DATA_BASE_BYTES
        self.data_limit_bytes = DEFAULT_DATA_LIMIT_BYTES
        self.input_start = 0
        self.input_stride = 1
        self.clear_state = True

    @property
    def data_word_count(self) -> int:
        return self.num_values + 1

    @property
    def diff_word_count(self) -> int:
        return self.num_values

    @property
    def total_word_count(self) -> int:
        return self.data_word_count + self.diff_word_count

    @property
    def data_base_word(self) -> int:
        return self.data_base_bytes // 4

    @property
    def diff_base_word(self) -> int:
        return self.data_base_word + self.data_word_count

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        group = parser.add_argument_group("adjacent-differences FPGA options")

        group.add_argument(
            "--num-values",
            type=int,
            default=DEFAULT_NUM_VALUES,
            help="Number of adjacent differences to compute, default: 32",
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
            "--input-start",
            type=int,
            default=0,
            help="First logical input value, default: 0",
        )
        group.add_argument(
            "--input-stride",
            type=int,
            default=1,
            help="Difference between consecutive logical input values, default: 1",
        )
        group.add_argument(
            "--no-clear-state",
            action="store_true",
            help="Do not clear the data/diff region before initializing data[]",
        )

    def configure(
        self,
        *,
        kernel_calls: int,
        visualize: bool,
        adapter_args: argparse.Namespace,
    ) -> None:
        if adapter_args.num_values < 1:
            raise SystemExit("--num-values must be >= 1")
        if adapter_args.data_base % 4 != 0:
            raise SystemExit("--data-base must be 4-byte aligned")
        if adapter_args.data_limit % 4 != 0:
            raise SystemExit("--data-limit must be 4-byte aligned")
        if adapter_args.data_limit <= adapter_args.data_base:
            raise SystemExit("--data-limit must be greater than --data-base")

        self.num_values = adapter_args.num_values
        self.data_base_bytes = adapter_args.data_base
        self.data_limit_bytes = adapter_args.data_limit
        self.input_start = adapter_args.input_start
        self.input_stride = adapter_args.input_stride
        self.clear_state = not adapter_args.no_clear_state

        available_words = (self.data_limit_bytes - self.data_base_bytes) // 4
        if available_words < self.total_word_count:
            raise SystemExit(
                f"differences needs {self.total_word_count} words at --data-base "
                f"for data[{self.data_word_count}] + diff[{self.diff_word_count}], "
                f"but only {available_words} words are available"
            )

        with self.csv_path.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["call", "index", "data_left", "data_right", "diff", "expected", "ok"])

        print(
            f"[INFO] differences adapter: kernel_calls={kernel_calls}, "
            f"num_values={self.num_values}, "
            f"data_base=0x{self.data_base_bytes:08x}, "
            f"diff_base_word={self.diff_base_word}"
        )

    def build_data_words(self) -> list[str]:
        values = [0]

        for i in range(self.num_values):
            values.append(self.input_start + i * self.input_stride)

        return [u32_hex(v) for v in values]

    def initial_dmem(self):
        updates: list[tuple[int, list[str]]] = []

        if self.clear_state:
            updates.append(
                (
                    self.data_base_word,
                    [u32_hex(0)] * self.total_word_count,
                )
            )

        # Host-side initialization of data[] avoids any need for a cross-lane
        # barrier in the kernel before computing diff[].
        updates.append(
            (
                self.data_base_word,
                self.build_data_words(),
            )
        )

        return updates

    def kernel_arguments(
        self,
        *,
        call_index: int,
        adapter_args: argparse.Namespace,
    ):
        return [
            self.data_base_bytes,  # GPGPU_ARGS[0]: byte pointer to data[] and diff[]
            self.num_values,       # GPGPU_ARGS[1]: number of output differences
            0,                     # GPGPU_ARGS[2]: reserved
            0,                     # GPGPU_ARGS[3]: reserved
        ]

    def output_window(
        self,
        *,
        call_index: int,
        kernel_args: list[str],
        adapter_args: argparse.Namespace,
    ) -> DmemWindow:
        # Dump data[] + diff[] so we can verify the result in process_output().
        return DmemWindow(
            byte_address=self.data_base_bytes,
            word_count=self.total_word_count,
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
        rows = []

        for i in range(self.num_values):
            left_addr = self.data_base_word + i
            right_addr = self.data_base_word + i + 1
            diff_addr = self.diff_base_word + i

            missing = [addr for addr in (left_addr, right_addr, diff_addr) if addr not in words]
            if missing:
                raise RuntimeError(f"Missing dumped DMEM word(s): {missing}")

            data_left = int32_from_hex(words[left_addr])
            data_right = int32_from_hex(words[right_addr])
            diff = int32_from_hex(words[diff_addr])
            expected = data_right - data_left
            ok = int(diff == expected)

            rows.append([call_index, i, data_left, data_right, diff, expected, ok])

        with self.csv_path.open("a", newline="") as f:
            writer = csv.writer(f)
            writer.writerows(rows)

        failures = sum(1 for row in rows if row[-1] == 0)
        if failures:
            print(f"[ERROR] differences call {call_index}: {failures} mismatches written to {self.csv_path}")
        else:
            print(f"[INFO] differences call {call_index}: all {self.num_values} outputs correct")

    def finalize(self, *, visualize: bool, adapter_args: argparse.Namespace) -> None:
        if not visualize:
            return

        visualize_script = self.program_dir / "visualize.py"
        if not visualize_script.exists():
            print("[INFO] No visualize.py found; skipping visualization")
            return

        print(f"[INFO] Running visualization: {visualize_script}")
        subprocess.run([sys.executable, str(visualize_script)], cwd=self.program_dir, check=True)
