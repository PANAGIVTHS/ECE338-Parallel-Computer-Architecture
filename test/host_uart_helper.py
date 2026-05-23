#!/usr/bin/env python3

import argparse
import sys
import time
from pathlib import Path
import serial
import struct

RET_INSTR = "00008067"

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

class GpgpuUart:
    def __init__(self, port, baud, timeout=2.0, verbose=False):
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
        self.ser.write((line + "\r\n").encode("ascii"))
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

def main():
    parser = argparse.ArgumentParser(description="GPGPU Hardware Helper Utility")
    parser.add_argument("--port", required=True, help="Serial port, e.g. /dev/ttyUSB1")
    parser.add_argument("--baud", type=int, default=115200, help="Baud rate (default: 115200)")
    parser.add_argument("--verbose", action="store_true", help="Print all UART traffic")

    # Create subcommands for the different actions
    subparsers = parser.add_subparsers(dest="command", required=True, help="Action to perform")

    # Command: clean-imem
    cmd_clean_imem = subparsers.add_parser("clean-imem", help="Fill IMEM with zeros")
    cmd_clean_imem.add_argument("--size", type=int, default=2048, help="Number of words to clear (default: 2048)")

    # Command: clean-dmem
    cmd_clean_dmem = subparsers.add_parser("clean-dmem", help="Fill DMEM with zeros")
    cmd_clean_dmem.add_argument("--size", type=int, default=2048, help="Number of words to clear (default: 2048)")

    # Command: load-imem
    cmd_load_imem = subparsers.add_parser("load-imem", help="Load a .mem file into IMEM")
    cmd_load_imem.add_argument("file", type=Path, help="Path to the .mem file")
    cmd_load_imem.add_argument("--trim", action="store_true", help="Stop loading after seeing the RET instruction")

    # Command: load-dmem
    cmd_load_dmem = subparsers.add_parser("load-dmem", help="Load a .mem file into DMEM")
    cmd_load_dmem.add_argument("file", type=Path, help="Path to the .mem file")

    args = parser.parse_args()

    print(f"[INFO] Opening UART {args.port} @ {args.baud}...")
    uart = GpgpuUart(args.port, args.baud, verbose=args.verbose)

    try:
        if args.command == "clean-imem":
            print(f"[INFO] Cleaning IMEM ({args.size} words)...")
            zeros = ["00000000"] * args.size
            uart.load_imem(zeros)
            print("[SUCCESS] IMEM wiped.")

        elif args.command == "clean-dmem":
            print(f"[INFO] Cleaning DMEM ({args.size} words)...")
            zeros = ["00000000"] * args.size
            uart.load_dmem(zeros)
            print("[SUCCESS] DMEM wiped.")

        elif args.command == "load-imem":
            if not args.file.exists():
                print(f"[ERROR] File not found: {args.file}")
                return 1
            
            words = read_mem_file(args.file)
            if args.trim:
                words = trim_program_at_ret(words)
            
            print(f"[INFO] Loading {len(words)} words into IMEM from {args.file.name}...")
            uart.load_imem(words)
            print("[SUCCESS] IMEM load complete.")

        elif args.command == "load-dmem":
            if not args.file.exists():
                print(f"[ERROR] File not found: {args.file}")
                return 1
            
            words = read_mem_file(args.file)
            print(f"[INFO] Loading {len(words)} words into DMEM from {args.file.name}...")
            uart.load_dmem(words)
            print("[SUCCESS] DMEM load complete.")

    except Exception as e:
        print(f"\n[ERROR] Operation failed: {e}")
        return 1
    finally:
        uart.close()

    return 0

if __name__ == "__main__":
    sys.exit(main())