"""FPGA adapter for memspaces: checks every memory space of linker.ld on the board.

The runner loads the program once (IMEM, .rodata/.data into GMEM, .bss and
.shared zeroed), then this adapter launches the kernel --kernel-calls times
with op = (call index + --op) % 7 and checks, after each launch:

  out[]       (.shared, DMEM)  against the formula in memspaces.c
  call_count  (.data, GMEM)    100 + launches so far

Launch k sees the globals launch k - 1 left (slots[], call_count): that is
what "once per program load" means. Any mismatch fails the run.

    python software/programs/fpga_run.py -p memspaces --port /dev/ttyUSB0 --kernel-calls 4
"""

from __future__ import annotations

import argparse

from fpga_run import ProgramAdapter as BaseProgramAdapter

CORES = 32
GAIN = [3, 1, 4, 1, 5, 9, 2, 6]
BIAS = [1000, 2000, 3000, 4000]


def op_result(op: int, tid: int) -> int:
    return {0: tid, 1: tid * 3, 2: tid + 77, 3: -tid, 4: tid << 4, 5: tid ^ 0x55}.get(op, 0)


def expected_out(launch: int, op: int) -> list[int]:
    return [(op_result(op, tid) + GAIN[tid & 7] + BIAS[tid & 3] + 100 + launch
             + (tid + 1 if launch else 0) + 4 * tid + 6) & 0xFFFFFFFF for tid in range(CORES)]


class ProgramAdapter(BaseProgramAdapter):
    def __init__(self, program_dir, artifact_dir):
        super().__init__(program_dir, artifact_dir)
        self.first_op = 0
        self.failures = 0

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument_group("memspaces FPGA options").add_argument(
            "--op", type=int, default=0, help="op of the first launch (0..6); later launches add 1 each")

    def configure(self, *, kernel_calls, visualize, adapter_args) -> None:
        self.first_op = adapter_args.op
        for name in ("out", "call_count", "slots", "gain", "bias"):
            print(f"[INFO] {name:<10} at 0x{self.symbol(name):08x} ({self.layout['symbols'][name]['section']})")

    def op(self, call_index: int) -> int:
        return (self.first_op + call_index) % 7

    def kernel_arguments(self, *, call_index, adapter_args):
        return [self.op(call_index)]

    def after_call(self, *, uart, call_index, kernel_args, adapter_args) -> None:
        gmem_base = self.layout["gmem_data"]["start"]
        offset = (self.symbol("call_count") - gmem_base) // 4
        value = int(uart.dump_gmem_bin(1, offset=offset)[offset], 16)
        expected = 101 + call_index
        status = "ok" if value == expected else "MISMATCH"
        self.failures += value != expected
        print(f"[CHECK] launch {call_index}: call_count = {value}, expected {expected}: {status}")

    def output_window(self, *, call_index, kernel_args, adapter_args):
        return self.symbol_window("out")

    def process_output(self, *, call_index, kernel_args, output_window, words, adapter_args) -> None:
        got = [int(words[output_window.word_offset + i], 16) for i in range(CORES)]
        expected = expected_out(call_index, self.op(call_index))
        bad = [tid for tid in range(CORES) if got[tid] != expected[tid]]
        self.failures += bool(bad)
        if bad:
            tid = bad[0]
            print(f"[CHECK] launch {call_index} op {self.op(call_index)}: out[] differs in {len(bad)} lanes, "
                  f"first lane {tid}: {got[tid]} instead of {expected[tid]}")
        else:
            print(f"[CHECK] launch {call_index} op {self.op(call_index)}: out[] ok ({CORES} lanes)")

    def finalize(self, *, visualize, adapter_args) -> None:
        if self.failures:
            raise SystemExit(f"[FAIL] memspaces: {self.failures} check(s) failed")
        print("[PASS] memspaces: .rodata, .data, .bss, .shared, stack and GPGPU_ARGS behave as linker.ld says")
