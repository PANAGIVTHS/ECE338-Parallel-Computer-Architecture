#!/usr/bin/env python3

import argparse
import sys
from pathlib import Path

BAREMETAL_DIR = Path(__file__).resolve().parents[1] / "host" / "baremetal"
sys.path.insert(0, str(BAREMETAL_DIR))

from gpgpu_uart import DEPTH, GpgpuUartMonitor as GpgpuUart, read_mem_file, trim_program_at_ret


def discover_tests(tests_root: Path):
    tests = []
    idx = 1

    while True:
        test_dir = tests_root / f"test{idx}"
        program = test_dir / "program.mem"
        expected = test_dir / "data.mem"

        if not program.exists():
            break

        if not expected.exists():
            raise FileNotFoundError(f"Missing expected DMEM file: {expected}")

        tests.append((idx, test_dir, program, expected))
        idx += 1

    return tests


def compare_dmem(test_idx, got, expected_words, check_count=None, offset=0):
    if check_count is None:
        check_count = len(expected_words) - offset

    errors = 0

    for addr in range(offset, offset + check_count):
        exp = expected_words[addr].lower().zfill(8)[-8:]
        act = got.get(addr)

        if act is None:
            print(f"[FAIL] test{test_idx} DMEM[{addr}]: missing from dump, expected {exp}")
            errors += 1
            continue

        if act != exp:
            print(f"[FAIL] test{test_idx} DMEM[{addr}]: expected {exp}, got {act}")
            errors += 1

    return errors


def main():
    parser = argparse.ArgumentParser(description="Run GPGPU tests through UART monitor.")
    parser.add_argument("--port", required=True, help="Serial port, e.g. /dev/ttyUSB1 or COM5")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--tests-root", default="tests")
    parser.add_argument("--dmem-words", type=int, default=2048)
    parser.add_argument("--dmem-offset", type=int, default=0, help="DMEM word offset to dump/compare (default: 0)")
    parser.add_argument("--check-words", type=int, default=None,
                        help="Only compare N dumped DMEM words. Default: compare the full dumped range.")
    parser.add_argument("--start-at", type=int, default=1, help="Test index to start running from (default: 1)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    tests_root = Path(args.tests_root)
    tests = discover_tests(tests_root)

    if not tests:
        print(f"[ERROR] No tests found under {tests_root}")
        return 1

    print(f"[INFO] Found {len(tests)} tests.")
    print(f"[INFO] Opening UART {args.port} @ {args.baud}...")

    uart = GpgpuUart(args.port, args.baud, verbose=args.verbose)

    total_errors = 0

    try:
        for test_idx, test_dir, program_path, expected_path in tests:
            if test_idx < args.start_at:
                continue
            print(f"\n[INFO] Running test{test_idx} through UART...")

            program = trim_program_at_ret(read_mem_file(program_path))
            data_words = ["00000000"] * DEPTH

            expected = read_mem_file(expected_path)
            if len(expected) < args.dmem_words:
                expected = expected + ["00000000"] * (args.dmem_words - len(expected))

            print(f"[INFO] Loading {len(program)} IMEM words at offset 0...")
            uart.load_imem_bin(program, offset=0)

            print(f"[INFO] Loading {len(data_words)} DMEM words at offset 0...")
            uart.load_dmem_bin(data_words, offset=0)

            print("[INFO] Starting core...")
            uart.run()

            print(f"[INFO] Dumping {args.dmem_words} DMEM words at offset {args.dmem_offset}...")
            dmem = uart.dump_dmem_bin(args.dmem_words, offset=args.dmem_offset)

            check_count = args.check_words
            if check_count is None:
                check_count = args.dmem_words

            errors = compare_dmem(test_idx, dmem, expected, check_count=check_count, offset=args.dmem_offset)

            print("[INFO] Sending done...")
            uart.done()

            if errors == 0:
                print(f"[PASS] test{test_idx}")
            else:
                print(f"[FAIL] test{test_idx}: {errors} DMEM mismatches")
                total_errors += errors

    finally:
        uart.close()

    if total_errors:
        print(f"\n[ERROR] UART test run failed with {total_errors} total errors.")
        return 1

    print("\n[SUCCESS] All UART tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
