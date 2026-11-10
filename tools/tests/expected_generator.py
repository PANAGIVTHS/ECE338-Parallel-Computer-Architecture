"""Generate each case's expected results by running it on the GPGPU model.

Inputs per case directory (cases/test<N>/):
  program.mem    the assembled program (assembler.py), one hex word per line
  dmem_seed.mem  optional initial DMEM: hex words, '@<word index>' moves on
  ddr_seed.mem   optional initial DDR: '<byte address> <word>' hex pairs

Outputs:
  regfile_c<lane>.mem  every lane's registers after the kernel
  data.mem             all of DMEM after the kernel
  ddr.mem              only for cases that use DDR: 'bursts <n>' (AXI write
                       bursts the kernel issues), then every DDR word, seeded
                       or written, as '<byte address> <word>' hex pairs
  perf.mem             the model's counts for the performance counters, as
                       '<name> <decimal count>' lines: 'instructions' (warp
                       instructions executed, RET included), then
                       'ddr_lane_stores' (lane stores to DDR)

A case must end with RET and must not fault: fault reporting is checked by
the E2E bench's directed fault kernels. The model and its rules are in
gpgpu_model.py.
"""

import argparse
from pathlib import Path
import re
import sys

from gpgpu_model import ModelError, Warp, read_constants


def format_hex(value):
    return f"{value & 0xFFFFFFFF:08x}"


def _code(line):
    return line.split('#')[0].split('//')[0].strip()


def load_program(path):
    return [int(token, 16) for line in path.read_text(encoding='utf-8').splitlines()
            for token in _code(line).split()]


def load_dmem_seed(path, depth):
    """$readmemh subset: one word per token, '@<hex word index>' sets the index."""
    memory = [0] * depth
    addr = 0
    for line_no, line in enumerate(path.read_text(encoding='utf-8').splitlines(), start=1):
        for token in _code(line).split():
            if token.startswith('@'):
                addr = int(token[1:], 16)
                if addr >= depth:
                    raise ValueError(f"{path}:{line_no}: seed address @{addr:x} outside DMEM depth {depth}")
                continue
            if addr >= depth:
                raise ValueError(f"{path}:{line_no}: too many seed words for DMEM depth {depth}")
            memory[addr] = int(token, 16) & 0xFFFFFFFF
            addr += 1
    return memory


def load_ddr_seed(path):
    """'<byte address> <word>' hex pairs, word-aligned addresses."""
    words = {}
    for line_no, line in enumerate(path.read_text(encoding='utf-8').splitlines(), start=1):
        code = _code(line)
        if not code:
            continue
        match = re.fullmatch(r'([0-9a-fA-F]+)\s+([0-9a-fA-F]+)', code)
        if match is None:
            raise ValueError(f"{path}:{line_no}: expected '<address> <word>' in hex, found {code!r}")
        addr, value = int(match[1], 16), int(match[2], 16)
        if addr & 3:
            raise ValueError(f"{path}:{line_no}: address {addr:#x} is not word-aligned")
        words[addr] = value & 0xFFFFFFFF
    return words


def generate_case(test_dir, num_cores, constants, max_instructions):
    """Run one case on the model and write its expected files."""
    program = load_program(test_dir / 'program.mem')
    dmem_seed_path = test_dir / 'dmem_seed.mem'
    ddr_seed_path = test_dir / 'ddr_seed.mem'
    dmem_seed = (load_dmem_seed(dmem_seed_path, constants['gpu_pkg::DMEM_ENTRIES'])
                 if dmem_seed_path.is_file() else None)
    ddr_seed = load_ddr_seed(ddr_seed_path) if ddr_seed_path.is_file() else {}

    result = Warp(program, num_cores, constants, dmem_seed, ddr_seed).run(max_instructions)
    if result.fault is not None:
        raise ModelError(
            f"the kernel faults at PC {result.fault.pc:#x} (lanes {result.fault.lanes:#x}, "
            f"status {sorted(result.fault.statuses)}); test cases must complete cleanly")
    for pc in result.divergent_pcs:
        print(f"  [WARNING] lanes disagree on the branch at PC {pc:#x}; "
              f"the hardware follows lane 0 and so does the model")

    for stale in test_dir.glob('regfile_c*.mem'):
        stale.unlink()
    for lane, regs in enumerate(result.regfiles):
        (test_dir / f'regfile_c{lane}.mem').write_text(''.join(format_hex(v) + '\n' for v in regs))
    (test_dir / 'data.mem').write_text(''.join(format_hex(v) + '\n' for v in result.dmem))

    (test_dir / 'perf.mem').write_text(f'instructions {result.instructions}\n'
                                       f'ddr_lane_stores {result.ddr_lane_stores}\n')

    ddr_path = test_dir / 'ddr.mem'
    if ddr_seed or result.ddr or result.ddr_bursts:
        lines = [f'bursts {result.ddr_bursts}']
        lines += [f'{format_hex(addr)} {format_hex(value)}' for addr, value in result.ddr.items()]
        ddr_path.write_text('\n'.join(lines) + '\n')
    elif ddr_path.exists():
        ddr_path.unlink()
    return result


def main():
    parser = argparse.ArgumentParser(description="Generate expected results with the GPGPU model")
    parser.add_argument("target_dir", nargs="?", help="Optional single test directory")
    parser.add_argument("--num-cores", type=int, required=True,
                        help="Number of streaming processors (lanes)")
    parser.add_argument("--rtl-constants", type=Path, required=True,
                        help="RTL package constants written by tests:rtl:constants")
    parser.add_argument("--max-instructions", type=int, default=100_000,
                        help="Warp instructions before a case is reported as not ending")
    args = parser.parse_args()
    if args.num_cores < 1:
        parser.error("--num-cores must be at least 1")

    constants = read_constants(args.rtl_constants)
    if args.target_dir:
        test_dirs = [Path(args.target_dir)]
    else:
        test_dirs = sorted((path.parent for path in Path('.').glob('cases/test*/program.mem')
                            if re.fullmatch(r'test\d+', path.parent.name)),
                           key=lambda path: int(path.name.removeprefix('test')))
    if not test_dirs:
        print("No assembled 'program.mem' files found in 'cases/test<N>' directories.")
        return 1

    print(f"Found {len(test_dirs)} tests. Running them on the model with {args.num_cores} lanes...\n")
    failures = 0
    for test_dir in test_dirs:
        try:
            result = generate_case(test_dir, args.num_cores, constants, args.max_instructions)
        except (ModelError, OSError, ValueError) as error:
            print(f"  [Error] {test_dir}: {error}")
            failures += 1
            continue
        ddr = f", {len(result.ddr)} DDR words in {result.ddr_bursts} bursts" if (test_dir / 'ddr.mem').exists() else ""
        print(f"  {test_dir}: {result.instructions} instructions{ddr}")

    if failures:
        print(f"\n{failures} case(s) could not be generated.")
        return 1
    print("\nExpected results generated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
