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
        self.rx_buffer = bytearray()
        time.sleep(0.2)
        self.flush()

    def flush(self):
        self.rx_buffer.clear()
        self.ser.reset_input_buffer()
        self.ser.reset_output_buffer()

    def close(self):
        self.ser.close()

    def write_line(self, line: str):
        if self.verbose:
            print(f">>> {line}")
        self.ser.write((line + "\r\n").encode("ascii"))
        self.ser.flush()

    def _read_from_serial(self, timeout=20.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            n = self.ser.in_waiting
            chunk = self.ser.read(n if n else 1)
            if chunk:
                self.rx_buffer.extend(chunk)
                return
        raise TimeoutError("Timed out waiting for UART data")

    def read_available(self, delay=0.05):
        time.sleep(delay)
        n = self.ser.in_waiting
        if n:
            self.rx_buffer.extend(self.ser.read(n))
        if not self.rx_buffer:
            self._read_from_serial(timeout=getattr(self.ser, "timeout", 2.0) or 2.0)
        data = bytes(self.rx_buffer)
        self.rx_buffer.clear()
        text = data.decode("ascii", errors="replace")
        if self.verbose and text:
            print(text, end="")
        return text

    def read_until_bytes(self, patterns, timeout=20.0):
        if isinstance(patterns, bytes):
            patterns = [patterns]
        else:
            patterns = [p.encode("ascii") if isinstance(p, str) else p for p in patterns]

        deadline = time.time() + timeout

        while time.time() < deadline:
            for p in patterns:
                idx = self.rx_buffer.find(p)
                if idx != -1:
                    end = idx + len(p)
                    out = bytes(self.rx_buffer[:end])
                    del self.rx_buffer[:end]
                    if self.verbose:
                        print(out.decode("ascii", errors="replace"), end="")
                    return out, p

            self._read_from_serial(timeout=max(0.0, deadline - time.time()))

        preview = bytes(self.rx_buffer).decode("ascii", errors="replace")
        raise TimeoutError(f"Timed out waiting for one of {patterns}. Last output:\n{preview}")

    def read_exact(self, count, timeout=20.0):
        deadline = time.time() + timeout
        while len(self.rx_buffer) < count:
            self._read_from_serial(timeout=max(0.0, deadline - time.time()))

        out = bytes(self.rx_buffer[:count])
        del self.rx_buffer[:count]
        return out

    def read_until(self, patterns, timeout=20.0):
        if isinstance(patterns, str):
            byte_patterns = [patterns.encode("ascii")]
        else:
            byte_patterns = [p.encode("ascii") for p in patterns]

        out, matched = self.read_until_bytes(byte_patterns, timeout=timeout)
        return out.decode("ascii", errors="replace"), matched.decode("ascii", errors="replace")

    def wait_prompt(self, timeout=20.0):
        return self.read_until("gpgpu>", timeout=timeout)[0]

    def load_imem(self, program_words, offset=0):
        self.write_line(f"loadimem_bin {offset} {len(program_words)}")
        output, marker = self.read_until(["READY_IMEM_BIN", "ERROR"], timeout=5.0)
        if marker == "ERROR":
            raise RuntimeError(f"IMEM load rejected:\n{output}")

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

    def load_dmem(self, data_words, offset=0):
        self.write_line(f"loaddmem_bin {offset} {len(data_words)}")
        output, marker = self.read_until(["READY_DMEM_BIN", "ERROR"], timeout=5.0)
        if marker == "ERROR":
            raise RuntimeError(f"DMEM load rejected:\n{output}")

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
    cmd_clean_imem.add_argument("--offset", type=int, default=0, help="Starting IMEM word offset (default: 0)")

    # Command: clean-dmem
    cmd_clean_dmem = subparsers.add_parser("clean-dmem", help="Fill DMEM with zeros")
    cmd_clean_dmem.add_argument("--size", type=int, default=2048, help="Number of words to clear (default: 2048)")
    cmd_clean_dmem.add_argument("--offset", type=int, default=0, help="Starting DMEM word offset (default: 0)")

    # Command: load-imem
    cmd_load_imem = subparsers.add_parser("load-imem", help="Load a .mem file into IMEM")
    cmd_load_imem.add_argument("file", type=Path, help="Path to the .mem file")
    cmd_load_imem.add_argument("--offset", type=int, default=0, help="Starting IMEM word offset (default: 0)")
    cmd_load_imem.add_argument("--trim", action="store_true", help="Stop loading after seeing the RET instruction")

    # Command: load-dmem
    cmd_load_dmem = subparsers.add_parser("load-dmem", help="Load a .mem file into DMEM")
    cmd_load_dmem.add_argument("file", type=Path, help="Path to the .mem file")
    cmd_load_dmem.add_argument("--offset", type=int, default=0, help="Starting DMEM word offset (default: 0)")

    args = parser.parse_args()

    print(f"[INFO] Opening UART {args.port} @ {args.baud}...")
    uart = GpgpuUart(args.port, args.baud, verbose=args.verbose)

    try:
        if args.command == "clean-imem":
            print(f"[INFO] Cleaning IMEM ({args.size} words at offset {args.offset})...")
            zeros = ["00000000"] * args.size
            uart.load_imem(zeros, offset=args.offset)
            print("[SUCCESS] IMEM wiped.")

        elif args.command == "clean-dmem":
            print(f"[INFO] Cleaning DMEM ({args.size} words at offset {args.offset})...")
            zeros = ["00000000"] * args.size
            uart.load_dmem(zeros, offset=args.offset)
            print("[SUCCESS] DMEM wiped.")

        elif args.command == "load-imem":
            if not args.file.exists():
                print(f"[ERROR] File not found: {args.file}")
                return 1
            
            words = read_mem_file(args.file)
            if args.trim:
                words = trim_program_at_ret(words)
            
            print(f"[INFO] Loading {len(words)} words into IMEM[{args.offset}..{args.offset + len(words) - 1}] from {args.file.name}...")
            uart.load_imem(words, offset=args.offset)
            print("[SUCCESS] IMEM load complete.")

        elif args.command == "load-dmem":
            if not args.file.exists():
                print(f"[ERROR] File not found: {args.file}")
                return 1
            
            words = read_mem_file(args.file)
            print(f"[INFO] Loading {len(words)} words into DMEM[{args.offset}..{args.offset + len(words) - 1}] from {args.file.name}...")
            uart.load_dmem(words, offset=args.offset)
            print("[SUCCESS] DMEM load complete.")

    except Exception as e:
        print(f"\n[ERROR] Operation failed: {e}")
        return 1
    finally:
        uart.close()

    return 0

if __name__ == "__main__":
    sys.exit(main())