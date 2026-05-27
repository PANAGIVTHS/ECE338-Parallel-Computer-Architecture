#!/usr/bin/env python3
"""Python UART client for the baremetal GPGPU host monitor.

This module intentionally mirrors the command surface printed by
host/baremetal/main.c so demo/test scripts do not need to hardcode UART
protocol details independently.
"""

from __future__ import annotations

import re
import struct
import time
from pathlib import Path
from typing import Iterable, cast

try:
    import serial
except ImportError:  # Allow --help and unit tests on machines without pyserial.
    serial = None

RET_INSTR = "00008067"
DEPTH = 2048
PROMPT = "gpgpu>"


def normalize_word(word: int | str) -> str:
    """Return *word* as exactly 8 lowercase hexadecimal digits."""
    if isinstance(word, int):
        value = word
    else:
        text = str(word).strip().lower()
        value = int(text, 16) if text.startswith("0x") else int(text, 16)
    return f"{value & 0xFFFFFFFF:08x}"


def words_to_le_bytes(words: Iterable[int | str]) -> bytes:
    data = bytearray()
    for word in words:
        data.extend(struct.pack("<I", int(normalize_word(word), 16)))
    return bytes(data)


def parse_memory_dump(text: str) -> dict[int, str]:
    """Parse ASCII dump lines like `0008: 00000014`."""
    result: dict[int, str] = {}
    pat = re.compile(r"^\s*(\d+):\s*([0-9a-fA-F]{8})\s*$")
    for line in text.splitlines():
        match = pat.match(line)
        if match:
            result[int(match.group(1), 10)] = match.group(2).lower()
    return result


def parse_single_word(text: str, mem_name: str, addr: int) -> str:
    pat = re.compile(rf"{re.escape(mem_name)}\[{addr}\]\s*=\s*0x([0-9a-fA-F]{{8}})")
    match = pat.search(text)
    if not match:
        raise RuntimeError(f"Could not parse {mem_name}[{addr}] from UART output:\n{text}")
    return match.group(1).lower()


def parse_status(text: str) -> dict[str, int | str]:
    status: dict[str, int | str] = {"text": text}
    raw = re.search(r"STATUS\s*=\s*0x([0-9a-fA-F]+)", text)
    if raw:
        status["raw"] = int(raw.group(1), 16)
    for name in ("loading", "running", "dumping", "busy", "done"):
        match = re.search(rf"\b{name}\s*=\s*([01])", text)
        if match:
            status[name] = int(match.group(1))
    return status


def read_mem_file(path: str | Path) -> list[str]:
    words: list[str] = []
    with Path(path).open("r") as f:
        for line in f:
            line = line.split("#")[0].strip()
            if line:
                words.append(normalize_word(line))
    return words


def write_mem_file(path: str | Path, words: dict[int, int | str] | Iterable[int | str]) -> None:
    with Path(path).open("w") as f:
        if isinstance(words, dict):
            word_map = cast(dict[int, int | str], words)
            for addr in sorted(word_map):
                f.write(f"{normalize_word(word_map[addr])}\n")
        else:
            for word in words:
                f.write(f"{normalize_word(word)}\n")


def trim_program_at_ret(words: Iterable[str]) -> list[str]:
    trimmed: list[str] = []
    for word in words:
        normalized = normalize_word(word)
        trimmed.append(normalized)
        if normalized == RET_INSTR:
            break
    return trimmed


class GpgpuUartMonitor:
    """High-level client for the commands exposed by the baremetal UART monitor."""

    def __init__(self, port: str, baud: int = 115200, timeout: float = 2.0, verbose: bool = False):
        if serial is None:
            raise RuntimeError("pyserial is required for UART access. Install it with `pip install pyserial`.")
        self.ser = serial.Serial(port, baudrate=baud, timeout=timeout)
        self.verbose = verbose
        self.rx_buffer = bytearray()
        time.sleep(0.2)
        self.flush()

    def flush(self) -> None:
        self.rx_buffer.clear()
        self.ser.reset_input_buffer()
        self.ser.reset_output_buffer()

    def close(self) -> None:
        self.ser.close()

    def __enter__(self) -> "GpgpuUartMonitor":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def write_line(self, line: str) -> None:
        if self.verbose:
            print(f">>> {line}")
        self.ser.write((line + "\n").encode("ascii"))
        self.ser.flush()

    def _read_from_serial(self, timeout: float = 20.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            n = self.ser.in_waiting
            chunk = self.ser.read(n if n else 1)
            if chunk:
                self.rx_buffer.extend(chunk)
                return
        raise TimeoutError("Timed out waiting for UART data")

    def read_available(self, delay: float = 0.05) -> str:
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

    def read_until_bytes(self, patterns, timeout: float = 20.0):
        if isinstance(patterns, bytes):
            patterns = [patterns]
        else:
            patterns = [p.encode("ascii") if isinstance(p, str) else p for p in patterns]

        deadline = time.time() + timeout
        while time.time() < deadline:
            for pattern in patterns:
                idx = self.rx_buffer.find(pattern)
                if idx != -1:
                    end = idx + len(pattern)
                    out = bytes(self.rx_buffer[:end])
                    del self.rx_buffer[:end]
                    if self.verbose:
                        print(out.decode("ascii", errors="replace"), end="")
                    return out, pattern
            self._read_from_serial(timeout=max(0.0, deadline - time.time()))

        preview = bytes(self.rx_buffer).decode("ascii", errors="replace")
        raise TimeoutError(f"Timed out waiting for one of {patterns}. Last output:\n{preview}")

    def read_exact(self, count: int, timeout: float = 20.0) -> bytes:
        deadline = time.time() + timeout
        while len(self.rx_buffer) < count:
            self._read_from_serial(timeout=max(0.0, deadline - time.time()))
        out = bytes(self.rx_buffer[:count])
        del self.rx_buffer[:count]
        return out

    def read_until(self, patterns, timeout: float = 20.0):
        if isinstance(patterns, str):
            byte_patterns = [patterns.encode("ascii")]
        else:
            byte_patterns = [p.encode("ascii") for p in patterns]
        out, matched = self.read_until_bytes(byte_patterns, timeout=timeout)
        return out.decode("ascii", errors="replace"), matched.decode("ascii", errors="replace")

    def wait_prompt(self, timeout: float = 20.0) -> str:
        return self.read_until(PROMPT, timeout=timeout)[0]

    def command(self, cmd: str, wait_for_prompt: bool = True, timeout: float = 20.0) -> str:
        self.write_line(cmd)
        if wait_for_prompt:
            return self.wait_prompt(timeout=timeout)
        return ""

    def _command_expect_prompt_or_error(self, cmd: str, timeout: float = 20.0) -> str:
        self.write_line(cmd)
        output, marker = self.read_until([PROMPT, "ERROR"], timeout=timeout)
        if marker == "ERROR":
            output += self.wait_prompt(timeout=timeout)
            raise RuntimeError(f"Command failed: {cmd}\n{output}")
        return output

    # General commands
    def help(self) -> str:
        return self.command("help")

    def status(self) -> dict[str, int | str]:
        return parse_status(self.command("status"))

    def run(self) -> str:
        self.write_line("run")
        output, marker = self.read_until(["Core entered dumping state", "ERROR"], timeout=30.0)
        if marker == "ERROR":
            raise RuntimeError(f"Run failed:\n{output}")
        return output + self.wait_prompt(timeout=10.0)

    def done(self) -> str:
        self.write_line("done")
        output, marker = self.read_until(["Returned to loading state", "ERROR"], timeout=20.0)
        if marker == "ERROR":
            raise RuntimeError(f"READ_DONE failed:\n{output}")
        return output + self.wait_prompt(timeout=10.0)

    # Single-word commands
    def write_imem(self, addr: int, word: int | str) -> str:
        return self._command_expect_prompt_or_error(f"wimem {addr} {normalize_word(word)}")

    def write_dmem(self, addr: int, word: int | str) -> str:
        return self._command_expect_prompt_or_error(f"wdmem {addr} {normalize_word(word)}")

    def read_imem(self, addr: int) -> str:
        return parse_single_word(self._command_expect_prompt_or_error(f"rimem {addr}"), "IMEM", addr)

    def read_dmem(self, addr: int) -> str:
        return parse_single_word(self._command_expect_prompt_or_error(f"rdmem {addr}"), "DMEM", addr)

    # ASCII bulk load/dump commands
    def load_imem_ascii(self, words: Iterable[int | str], offset: int = 0) -> str:
        return self._load_ascii("loadimem", "READY_FOR_BULK_IMEM", "IMEM_LOAD_COMPLETE", words, offset)

    def load_dmem_ascii(self, words: Iterable[int | str], offset: int = 0) -> str:
        return self._load_ascii("loaddmem", "READY_FOR_BULK_DMEM", "DMEM_LOAD_COMPLETE", words, offset)

    def _load_ascii(self, cmd: str, ready: str, complete: str, words: Iterable[int | str], offset: int) -> str:
        normalized = [normalize_word(word) for word in words]
        self.write_line(f"{cmd} {offset} {len(normalized)}")
        output, marker = self.read_until([ready, "ERROR"], timeout=5.0)
        if marker == "ERROR":
            raise RuntimeError(f"ASCII load rejected:\n{output}")
        for word in normalized:
            self.write_line(word)
        output2, marker2 = self.read_until([complete, "ERROR"], timeout=20.0)
        if marker2 == "ERROR":
            raise RuntimeError(f"ASCII load failed:\n{output + output2}")
        return output + output2

    def dump_imem_ascii(self, count: int, offset: int = 0) -> dict[int, str]:
        return parse_memory_dump(self._command_expect_prompt_or_error(f"dumpimem {offset} {count}"))

    def dump_dmem_ascii(self, count: int, offset: int = 0) -> dict[int, str]:
        return parse_memory_dump(self._command_expect_prompt_or_error(f"dumpdmem {offset} {count}"))

    # Binary bulk load/dump commands used by automated tests/demo.
    def load_imem_bin(self, words: Iterable[int | str], offset: int = 0) -> str:
        return self._load_binary("loadimem_bin", "READY_IMEM_BIN", "IMEM_LOAD_COMPLETE", words, offset)

    def load_dmem_bin(self, words: Iterable[int | str], offset: int = 0) -> str:
        return self._load_binary("loaddmem_bin", "READY_DMEM_BIN", "DMEM_LOAD_COMPLETE", words, offset)

    def _load_binary(self, cmd: str, ready: str, complete: str, words: Iterable[int | str], offset: int) -> str:
        normalized = [normalize_word(word) for word in words]
        self.write_line(f"{cmd} {offset} {len(normalized)}")
        output, marker = self.read_until([ready, "ERROR"], timeout=5.0)
        if marker == "ERROR":
            raise RuntimeError(f"Binary load rejected:\n{output}")
        payload = words_to_le_bytes(normalized)
        if self.verbose:
            print(f"[INFO] Bursting {len(payload)} raw bytes for {cmd}...")
        self.ser.write(payload)
        self.ser.flush()
        output2, marker2 = self.read_until([complete, "ERROR"], timeout=20.0)
        if marker2 == "ERROR":
            raise RuntimeError(f"Binary load failed:\n{output + output2}")
        return output + output2

    def dump_dmem_bin(self, count: int, offset: int = 0) -> dict[int, str]:
        self.write_line(f"dumpdmem_bin {offset} {count}")
        output, marker = self.read_until_bytes([b"BEGIN_DMEM_BIN\n", b"ERROR"], timeout=5.0)
        if marker == b"ERROR":
            raise RuntimeError(f"DMEM binary dump rejected:\n{output.decode('ascii', errors='replace')}")

        expected_bytes = count * 4
        raw_bytes = self.read_exact(expected_bytes, timeout=20.0)
        if len(raw_bytes) != expected_bytes:
            raise RuntimeError(f"Binary dump failed! Expected {expected_bytes} bytes, got {len(raw_bytes)}")

        result: dict[int, str] = {}
        for i in range(count):
            chunk = raw_bytes[i * 4 : (i + 1) * 4]
            value = struct.unpack("<I", chunk)[0]
            result[offset + i] = f"{value:08x}"

        self.wait_prompt(timeout=5.0)
        return result

    # Backwards-compatible aliases for the old scripts/tests.
    def load_imem(self, words: Iterable[int | str], offset: int = 0) -> str:
        return self.load_imem_bin(words, offset=offset)

    def load_dmem(self, words: Iterable[int | str], offset: int = 0) -> str:
        return self.load_dmem_bin(words, offset=offset)

    def dump_dmem(self, count: int, offset: int = 0) -> dict[int, str]:
        return self.dump_dmem_bin(count=count, offset=offset)


# Historical class name used by test scripts.
GpgpuUart = GpgpuUartMonitor
