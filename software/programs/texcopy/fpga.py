"""FPGA adapter for texcopy, the DDR read test.

    python software/programs/fpga_run.py -p texcopy --port /dev/ttyUSB1 [--fb 0]

1. `texfill <fb>` (host monitor): the A9 writes a test picture into the
   texture region, clears framebuffer fb and flushes its caches.
2. The kernel copies the picture from the texture (DDR reads) to framebuffer
   fb (DDR writes); the HDMI output shows it.
3. `texcheck <fb>`: the A9 compares the framebuffer with the texture word by
   word. Any difference fails the run.
4. `perf`: the counters of the run (DDR load stalls show as the LD_* leaves).

The addresses and the frame size come from the generated host header
(software/host/xc7z020/gpgpu_platform.h, task software:host:platform), the
same values the host monitor uses.
"""

from __future__ import annotations

import argparse
import re

from fpga_run import REPO_ROOT, ProgramAdapter as BaseProgramAdapter

PLATFORM_HEADER = REPO_ROOT / "software/host/xc7z020/gpgpu_platform.h"
_DEFINE = re.compile(r"^#define\s+GPGPU_(\w+)\s+(0x[0-9A-Fa-f]+|\d+)U?\s*$")


def read_platform() -> dict[str, int]:
    """The integer GPGPU_* defines of the host platform header."""
    values = {}
    for line in PLATFORM_HEADER.read_text().splitlines():
        match = _DEFINE.match(line)
        if match:
            values[match.group(1)] = int(match.group(2), 0)
    return values


class ProgramAdapter(BaseProgramAdapter):
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--fb", type=int, default=0, choices=(0, 1),
                            help="framebuffer to copy into and show (default 0)")

    def configure(self, *, kernel_calls: int, visualize: bool,
                  adapter_args: argparse.Namespace) -> None:
        platform = read_platform()
        self.fb_base = platform[f"FB{adapter_args.fb}_BASE"]
        self.tex_base = platform["TEX_BASE"]
        self.words = platform["FB_WIDTH"] * platform["FB_HEIGHT"]

    def before_calls(self, *, uart, adapter_args: argparse.Namespace) -> None:
        output, marker = self._command(uart, f"texfill {adapter_args.fb}", "TEXFILL_DONE")
        print(f"[INFO] {output.strip().splitlines()[-1]}")
        uart.command(f"display {adapter_args.fb}")

    def kernel_arguments(self, *, call_index: int, adapter_args: argparse.Namespace):
        return [self.fb_base, self.tex_base, self.words]

    def after_call(self, *, uart, call_index: int, kernel_args: list[str],
                   adapter_args: argparse.Namespace) -> None:
        output, marker = self._command(uart, f"texcheck {adapter_args.fb}",
                                       "TEXCHECK_PASS", "TEXCHECK_FAIL")
        if marker == "TEXCHECK_FAIL":
            raise RuntimeError(f"Framebuffer {adapter_args.fb} does not match the texture:\n{output}")
        print(f"[PASS] call {call_index + 1}: framebuffer {adapter_args.fb} matches the "
              f"texture ({self.words} words)")
        print(uart.command("perf"))

    def output_window(self, *, call_index: int, kernel_args: list[str],
                      adapter_args: argparse.Namespace):
        return None  # the result is in DDR, checked by texcheck

    @staticmethod
    def _command(uart, command: str, *markers: str) -> tuple[str, str]:
        """Send a monitor command; return its output up to the prompt and the
        marker it printed. A usage error or a missing marker raises."""
        uart.write_line(command)
        output, marker = uart.read_until([*markers, "ERROR"], timeout=60.0)
        output += uart.wait_prompt(timeout=60.0)
        if marker == "ERROR":
            raise RuntimeError(f"`{command}` failed:\n{output}")
        return output, marker
