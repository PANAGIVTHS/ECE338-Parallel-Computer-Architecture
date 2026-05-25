#!/usr/bin/env python3

import argparse
import re
import sys
import time
import struct
from pathlib import Path

try:
    import serial
except ImportError:
    serial = None

RET_INSTR = "00008067"
DEPTH = 2048

def read_mem_file(path: Path):
    words = []
    with path.open("r") as f:
        for line in f:
            line = line.split("#")[0].strip()
            if not line:
                continue
            words.append(line.lower().zfill(8)[-8:])
    return words


def trim_program_at_ret(words):
    trimmed = []
    for w in words:
        trimmed.append(w)
        if w.lower() == RET_INSTR:
            break
    return trimmed


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


class GpgpuUart:
    def __init__(self, port, baud, timeout=2.0, verbose=False):
        if serial is None:
            raise RuntimeError("pyserial is required for UART access. Install it with: python3 -m pip install pyserial")
        assert serial is not None
        self.ser = serial.Serial(port, baudrate=baud, timeout=timeout)
        self.verbose = verbose
        time.sleep(0.2)
        self.flush()

    def flush(self):
        self.ser.reset_input_buffer()
        self.ser.reset_output_buffer()

    def close(self):
        self.ser.close()

    def write_line(self, line: str):
        if self.verbose:
            print(f">>> {line}")
        self.ser.write((line + "\n").encode("ascii"))
        self.ser.flush()

    def read_available(self, delay=0.05):
        time.sleep(delay)
        data = self.ser.read(self.ser.in_waiting or 1)
        text = data.decode("ascii", errors="replace")
        if self.verbose and text:
            print(text, end="")
        return text

    def read_until(self, patterns, timeout=20.0):
        if isinstance(patterns, str):
            patterns = [patterns]

        deadline = time.time() + timeout
        buf = ""

        while time.time() < deadline:
            n = self.ser.in_waiting
            if n:
                chunk = self.ser.read(n).decode("ascii", errors="replace")
            else:
                chunk = self.ser.read(1).decode("ascii", errors="replace")

            if chunk:
                buf += chunk
                if self.verbose:
                    print(chunk, end="")

                for p in patterns:
                    if p in buf:
                        return buf, p

        raise TimeoutError(f"Timed out waiting for one of {patterns}. Last output:\n{buf}")

    def wait_prompt(self, timeout=20.0):
        return self.read_until("gpgpu>", timeout=timeout)[0]

    def command(self, cmd, wait_for_prompt=True, timeout=20.0):
        self.write_line(cmd)
        if wait_for_prompt:
            return self.wait_prompt(timeout=timeout)
        return ""
    
    def load_imem(self, program_words):
        self.write_line(f"loadimem_bin {len(program_words)}")
        self.read_until("READY_IMEM_BIN", timeout=5.0)

        byte_data = bytearray()
        for w in program_words:
            val = int(w, 16)
            byte_data.extend(struct.pack('<I', val))

        if self.verbose:
            print(f"[INFO] Bursting {len(byte_data)} raw bytes to IMEM...")

        self.ser.write(byte_data)
        self.ser.flush()

        output, _ = self.read_until("IMEM_LOAD_COMPLETE", timeout=10.0)
        return output

    def load_dmem(self, data_words):
        self.write_line(f"loaddmem_bin {len(data_words)}")
        self.read_until("READY_DMEM_BIN", timeout=5.0)

        byte_data = bytearray()
        for w in data_words:
            val = int(w, 16)
            byte_data.extend(struct.pack('<I', val))

        if self.verbose:
            print(f"[INFO] Bursting {len(byte_data)} raw bytes to DMEM...")

        self.ser.write(byte_data)
        self.ser.flush()

        output, _ = self.read_until("DMEM_LOAD_COMPLETE", timeout=10.0)
        return output

    def write_dmem_word(self, addr, word):
        self.command(f"wdmem {addr:x} {word & 0xffffffff:08x}", wait_for_prompt=True, timeout=5.0)

    def write_dmem_words(self, start_addr, words):
        for offset, word in enumerate(words):
            self.write_dmem_word(start_addr + offset, word)

    def run(self):
        self.write_line("run")
        output, _ = self.read_until(["Core entered dumping state", "ERROR"], timeout=30.0)
        if "ERROR" in output:
            raise RuntimeError(f"Run failed:\n{output}")
        output += self.wait_prompt(timeout=10.0)
        return output

    def done(self):
        self.write_line("done")
        output, _ = self.read_until(["Returned to loading state", "ERROR"], timeout=20.0)
        if "ERROR" in output:
            raise RuntimeError(f"READ_DONE failed:\n{output}")
        output += self.wait_prompt(timeout=10.0)
        return output

    def dump_dmem(self, count):
        self.write_line(f"dumpdmem_bin {count}")
        self.read_until("BEGIN_DMEM_BIN\n", timeout=5.0)

        expected_bytes = count * 4
        raw_bytes = self.ser.read(expected_bytes)
        if len(raw_bytes) != expected_bytes:
            raise RuntimeError(f"Binary dump failed! Expected {expected_bytes} bytes, got {len(raw_bytes)}")

        result = {}
        for i in range(count):
            chunk = raw_bytes[i*4 : (i+1)*4]
            val = struct.unpack('<I', chunk)[0]

            result[i] = f"{val:08x}"

        self.wait_prompt(timeout=5.0)
        return result


def parse_dmem_dump(text):
    result = {}

    # Matches: 0000: 00000000
    pat = re.compile(r"^\s*(\d+):\s*([0-9a-fA-F]{8})\s*$")

    for line in text.splitlines():
        m = pat.match(line)
        if m:
            addr = int(m.group(1), 10)
            value = m.group(2).lower()
            result[addr] = value

    return result


def compare_dmem(test_idx, got, expected_words, check_count=None):
    if check_count is None:
        check_count = len(expected_words)

    errors = 0

    for addr in range(check_count):
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
    parser.add_argument("--check-words", type=int, default=None,
                        help="Only compare first N DMEM words. Default: compare all expected words.")
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

            program = read_mem_file(program_path)
            program = trim_program_at_ret(program)
            data_words = ["00000000"] * DEPTH

            expected = read_mem_file(expected_path)
            if len(expected) < args.dmem_words:
                expected = expected + ["00000000"] * (args.dmem_words - len(expected))

            print(f"[INFO] Loading {len(program)} IMEM words...")
            uart.load_imem(program)

            print(f"[INFO] Loading {len(data_words)} DMEM words...")
            uart.load_dmem(data_words)

            print("[INFO] Starting core...")
            uart.run()

            print(f"[INFO] Dumping {args.dmem_words} DMEM words...")
            dmem = uart.dump_dmem(args.dmem_words)

            check_count = args.check_words
            if check_count is None:
                check_count = args.dmem_words

            errors = compare_dmem(test_idx, dmem, expected, check_count=check_count)

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