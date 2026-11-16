"""Run a kernel's RISC-V image on the GPGPU model against a run captured from a game's simulation.

A game's simulation (software/games/platform/sim) runs the native build of its
kernel. `<game>_sim --capture N DIR` saves the N-th run: the kernel's
arguments, and GMEM and the framebuffers before and after it. This script runs
the image the GPU would run, on the model the RTL tests use, from the memory
before, and checks what only the model can tell:

* every lane takes every branch the same way (the GPU has no divergence),
* no access faults (unmapped, write-only, misaligned),
* no two lanes store different values to one DDR byte in one instruction,
* the kernel uses only instructions the GPU has, and halts,

and that the memory it leaves is the memory the native build left, word for
word. It then prints what the run costs in instructions and AXI bursts.

    kernel_replay.py --image doom_instructions.mem --capture DIR --constants rtl_constants.txt
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from gpgpu_model import ModelError, Warp, read_constants

# The capture's files and the region each one holds (gpu_pkg base and size).
REGIONS = (("gmem", "GMEM_BASE", "GMEM_SIZE"), ("fb0", "FB0_BASE", "FB_SIZE"), ("fb1", "FB1_BASE", "FB_SIZE"))


class Snapshot:
    """The captured regions, read by byte address."""

    def __init__(self, directory: Path, when: str, constants: dict[str, int]):
        self.regions = []
        for name, base, size in REGIONS:
            data = (directory / f"{name}_{when}.bin").read_bytes()
            if len(data) > constants[f"gpu_pkg::{size}"]:
                raise SystemExit(f"{name}_{when}.bin is larger than gpu_pkg::{size}: rebuild the simulation against the RTL")
            self.regions.append((constants[f"gpu_pkg::{base}"], data))

    def word(self, address: int) -> int:
        """The word at a word-aligned byte address; 0 outside the capture."""
        for base, data in self.regions:
            offset = address - base
            if 0 <= offset < len(data):
                return int.from_bytes(data[offset:offset + 4].ljust(4, b"\0"), "little")
        return 0

    def words(self):
        """(address, word) of every captured word."""
        for base, data in self.regions:
            view = memoryview(data)
            for offset in range(0, len(data) - len(data) % 4, 4):
                yield base + offset, int.from_bytes(view[offset:offset + 4], "little")


class CapturedDdr(dict):
    """The model's sparse DDR, backed by the capture: a word nobody stored reads from it."""

    def __init__(self, snapshot: Snapshot):
        super().__init__()
        self._snapshot = snapshot

    def get(self, address, default=0):
        return self[address] if address in self else self._snapshot.word(address)


def replay(image: Path, capture: Path, constants_file: Path, cores: int, args_word: int, limit: int) -> int:
    constants = read_constants(constants_file)
    program = [int(line, 16) for line in image.read_text().split()]
    arguments = [int(line, 16) for line in (capture / "args.txt").read_text().split()]
    before, after = Snapshot(capture, "before", constants), Snapshot(capture, "after", constants)

    dmem = [0] * constants["gpu_pkg::DMEM_ENTRIES"]
    dmem[args_word:args_word + len(arguments)] = arguments
    warp = Warp(program, cores, constants, dmem_seed=dmem)
    warp.memory.ddr = CapturedDdr(before)

    try:
        result = warp.run(limit)
    except ModelError as error:
        print(f"FAIL: {error}")
        return 1

    failures = []
    if result.fault is not None:
        failures.append(f"fault at PC {result.fault.pc:#x}, lanes {result.fault.lanes:#010x}, "
                        f"status {sorted(result.fault.statuses)}")
    if result.divergent_pcs:
        pcs = sorted(set(result.divergent_pcs))
        failures.append(f"lanes disagree on {len(result.divergent_pcs)} branches, at PC "
                        + ", ".join(f"{pc:#x}" for pc in pcs[:8]) + (" ..." if len(pcs) > 8 else ""))

    # What the model stored must be what the native build left there, and
    # every word the native build changed must have been stored by the model.
    stored = result.ddr
    wrong = [(address, word, after.word(address)) for address, word in stored.items() if word != after.word(address)]
    changed = 0
    for (address, was), (_, now) in zip(before.words(), after.words()):
        if was != now:
            changed += 1
            if address not in stored:
                wrong.append((address, was, now))
    if wrong:
        failures.append(f"{len(wrong)} words differ from the native build's; first at {wrong[0][0]:#010x}: "
                        f"model {wrong[0][1]:#010x}, native {wrong[0][2]:#010x}")

    print(f"{image.name} on {cores} lanes: {result.instructions} instructions, "
          f"{len(stored)} words stored ({changed} changed)")
    print(f"  DDR stores: {result.ddr_lane_stores} lane stores in {result.ddr_bursts} bursts")
    print(f"  DDR loads:  {result.ddr_lane_loads} lane loads in {result.ddr_read_bursts} bursts, "
          f"{result.ddr_read_beats} beats")
    print(f"  DMEM:       {result.dmem_lane_accesses} lane accesses")
    for failure in failures:
        print(f"FAIL: {failure}")
    if not failures:
        print("PASS: no divergence, no fault, and the memory matches the native build")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--image", type=Path, required=True, help="the kernel's <program>_instructions.mem")
    parser.add_argument("--capture", type=Path, required=True, help="directory written by <game>_sim --capture")
    parser.add_argument("--constants", type=Path, required=True, help="rtl_constants.txt of `gpgpu rtl constants`")
    parser.add_argument("--cores", type=int, default=32)
    parser.add_argument("--args-word", type=int, default=16, help="DMEM word of GPGPU_ARGS[0] (__gpu_args_base / 4)")
    parser.add_argument("--limit", type=int, default=50_000_000, help="instructions before giving up")
    options = parser.parse_args()
    return replay(options.image, options.capture, options.constants, options.cores, options.args_word, options.limit)


if __name__ == "__main__":
    sys.exit(main())
