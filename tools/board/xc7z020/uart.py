#!/usr/bin/env python3
"""UART client for the GPGPU AXI4-Lite bare-metal monitor.

The PC still talks to the Zynq over UART. The Zynq application translates
commands to Xil_In32/Xil_Out32 accesses in one GPU AXI aperture; the host-PC
serial protocol is intentionally compatible with the older GPIO-based monitor.
"""

from __future__ import annotations

import re
import struct
import time
from pathlib import Path
from typing import Iterable, cast

try:
    import serial
except ImportError:
    serial = None  # Parsing helpers work without pyserial installed.

RET_INSTR = "00008067"
DEPTH = 2048
PROMPT = "gpgpu>"


def normalize_word(word: int | str) -> str:
    """Convert an integer or a hexadecimal string to eight hex digits."""
    value = word if isinstance(word, int) else int(str(word).strip(), 16)
    return f"{value & 0xFFFFFFFF:08x}"


def words_to_le_bytes(words: Iterable[int | str]) -> bytes:
    return b"".join(struct.pack("<I", int(normalize_word(w), 16)) for w in words)


def parse_memory_dump(text: str) -> dict[int, str]:
    result: dict[int, str] = {}
    for addr, word in re.findall(r"(?m)^\s*(\d+):\s*([0-9a-fA-F]{8})\s*$", text):
        result[int(addr, 10)] = word.lower()
    return result


def parse_single_word(text: str, mem_name: str, addr: int) -> str:
    pattern = rf"{re.escape(mem_name)}\[{addr}\]\s*=\s*0x([0-9a-fA-F]{{8}})"
    match = re.search(pattern, text)
    if not match:
        raise RuntimeError(f"Could not parse {mem_name}[{addr}] from UART output:\n{text}")
    return match.group(1).lower()


def parse_status(text: str) -> dict[str, int | str]:
    """New MMIO status fields: IDLE/RUNNING/STOPPED and IRQ enable/pending."""
    status: dict[str, int | str] = {"text": text}
    raw = re.search(r"(?m)^STATUS\s*=\s*0x([0-9a-fA-F]+)", text)
    info = re.search(r"(?m)^INFO\s*=\s*0x([0-9a-fA-F]+)", text)
    if raw:
        status["raw"] = int(raw.group(1), 16)
    if info:
        value = int(info.group(1), 16)
        status["info"] = value
        status["version"] = (value >> 16) & 0xFFFF
        status["cores"] = value & 0xFFFF
    for field in ("idle", "running", "stopped", "irq_enabled", "irq_pending"):
        match = re.search(rf"\b{field}\s*=\s*([01])", text)
        if match:
            status[field] = int(match.group(1))
    return status


def read_mem_file(path: str | Path) -> list[str]:
    words: list[str] = []
    with Path(path).open("r") as handle:
        for line in handle:
            line = line.split("#", 1)[0].strip()
            if line:
                words.append(normalize_word(line))
    return words


def write_mem_file(path: str | Path, words: dict[int, int | str] | Iterable[int | str]) -> None:
    with Path(path).open("w") as handle:
        if isinstance(words, dict):
            word_map = cast(dict[int, int | str], words)
            for index in sorted(word_map):
                handle.write(f"{normalize_word(word_map[index])}\n")
        else:
            for word in words:
                handle.write(f"{normalize_word(word)}\n")


def trim_program_at_ret(words: Iterable[str]) -> list[str]:
    result: list[str] = []
    for word in words:
        w = normalize_word(word)
        result.append(w)
        if w == RET_INSTR:
            break
    return result


def _check_index(index: int) -> None:
    if not 0 <= index < DEPTH:
        raise ValueError(f"GPU memory word index must be 0..{DEPTH - 1}, got {index}")


def _check_span(offset: int, count: int) -> None:
    if offset < 0 or count < 0 or offset > DEPTH or count > DEPTH - offset:
        raise ValueError(f"GPU memory range offset={offset}, count={count} exceeds {DEPTH} words")


class GpgpuUartMonitor:
    """High-level UART client for the Zynq monitor in baremetal/main.c."""

    def __init__(self, port: str, baud: int = 115200,
                 timeout: float = 2.0, verbose: bool = False):
        if serial is None:
            raise RuntimeError("Install pyserial to use the UART client: pip install pyserial")
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
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            count = self.ser.in_waiting
            chunk = self.ser.read(count if count else 1)
            if chunk:
                self.rx_buffer.extend(chunk)
                return
        raise TimeoutError("Timed out waiting for UART data")

    def read_available(self, delay: float = 0.05) -> str:
        time.sleep(delay)
        count = self.ser.in_waiting
        if count:
            self.rx_buffer.extend(self.ser.read(count))
        if not self.rx_buffer:
            self._read_from_serial(timeout=getattr(self.ser, "timeout", 2.0) or 2.0)
        out = bytes(self.rx_buffer).decode("ascii", errors="replace")
        self.rx_buffer.clear()
        if self.verbose and out:
            print(out, end="")
        return out

    def read_until_bytes(self, patterns, timeout: float = 20.0):
        if isinstance(patterns, (bytes, str)):
            patterns = [patterns]
        markers = [p.encode("ascii") if isinstance(p, str) else p for p in patterns]
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            # Return whichever marker occurs FIRST in the stream, not simply
            # the first in the marker list.
            found = [(pos, marker) for marker in markers
                     if (pos := self.rx_buffer.find(marker)) >= 0]
            if found:
                pos, marker = min(found, key=lambda pair: pair[0])
                end = pos + len(marker)
                out = bytes(self.rx_buffer[:end])
                del self.rx_buffer[:end]
                if self.verbose:
                    print(out.decode("ascii", errors="replace"), end="")
                return out, marker
            self._read_from_serial(timeout=max(0.0, deadline - time.monotonic()))
        preview = bytes(self.rx_buffer).decode("ascii", errors="replace")
        raise TimeoutError(f"Timed out waiting for {markers}. UART output:\n{preview}")

    def read_exact(self, count: int, timeout: float = 20.0) -> bytes:
        deadline = time.monotonic() + timeout
        while len(self.rx_buffer) < count:
            self._read_from_serial(timeout=max(0.0, deadline - time.monotonic()))
        data = bytes(self.rx_buffer[:count])
        del self.rx_buffer[:count]
        return data

    def read_until(self, patterns, timeout: float = 20.0):
        data, marker = self.read_until_bytes(patterns, timeout=timeout)
        return data.decode("ascii", errors="replace"), marker.decode("ascii", errors="replace")

    def wait_prompt(self, timeout: float = 20.0) -> str:
        return self.read_until(PROMPT, timeout=timeout)[0]

    def command(self, cmd: str, wait_for_prompt: bool = True, timeout: float = 20.0) -> str:
        self.write_line(cmd)
        return self.wait_prompt(timeout=timeout) if wait_for_prompt else ""

    def _command_expect_prompt_or_error(self, cmd: str, timeout: float = 20.0) -> str:
        self.write_line(cmd)
        output, marker = self.read_until([PROMPT, "ERROR"], timeout=timeout)
        if marker == "ERROR":
            output += self.wait_prompt(timeout=timeout)
            raise RuntimeError(f"Command failed: {cmd}\n{output}")
        return output

    def help(self) -> str:
        return self.command("help")

    def status(self) -> dict[str, int | str]:
        return parse_status(self._command_expect_prompt_or_error("status"))

    def run(self, timeout: float = 30.0) -> str:
        self.write_line("run")
        output, marker = self.read_until(["Core entered idle state.", "ERROR"], timeout=timeout)
        if marker == "ERROR":
            output += self.wait_prompt(timeout=5.0)
            raise RuntimeError(f"GPU run failed:\n{output}")
        return output + self.wait_prompt(timeout=5.0)

    # Single word indices in Python are DECIMAL integers. The existing UART
    # parser interprets single-word indices as HEX, so format with :x.
    def write_imem(self, addr: int, word: int | str) -> str:
        _check_index(addr)
        return self._command_expect_prompt_or_error(f"wimem {addr:x} {normalize_word(word)}")

    def write_dmem(self, addr: int, word: int | str) -> str:
        _check_index(addr)
        return self._command_expect_prompt_or_error(f"wdmem {addr:x} {normalize_word(word)}")

    def read_imem(self, addr: int) -> str:
        _check_index(addr)
        return parse_single_word(self._command_expect_prompt_or_error(f"rimem {addr:x}"), "IMEM", addr)

    def read_dmem(self, addr: int) -> str:
        _check_index(addr)
        return parse_single_word(self._command_expect_prompt_or_error(f"rdmem {addr:x}"), "DMEM", addr)

    def load_imem_ascii(self, words: Iterable[int | str], offset: int = 0) -> str:
        return self._load_ascii("loadimem", "READY_FOR_BULK_IMEM", "IMEM_LOAD_COMPLETE", words, offset)

    def load_dmem_ascii(self, words: Iterable[int | str], offset: int = 0) -> str:
        return self._load_ascii("loaddmem", "READY_FOR_BULK_DMEM", "DMEM_LOAD_COMPLETE", words, offset)

    def _load_ascii(self, cmd: str, ready: str, complete: str,
                    words: Iterable[int | str], offset: int) -> str:
        normalized = [normalize_word(w) for w in words]
        _check_span(offset, len(normalized))
        self.write_line(f"{cmd} {offset} {len(normalized)}")
        first, marker = self.read_until([ready, "ERROR"], timeout=5.0)
        if marker == "ERROR":
            raise RuntimeError(f"ASCII load rejected:\n{first + self.wait_prompt()}")
        for w in normalized:
            self.write_line(w)
        second, marker = self.read_until([complete, "ERROR"], timeout=60.0)
        if marker == "ERROR":
            raise RuntimeError(f"ASCII load failed:\n{first + second + self.wait_prompt()}")
        return first + second + self.wait_prompt(timeout=10.0)

    def dump_imem_ascii(self, count: int, offset: int = 0) -> dict[int, str]:
        _check_span(offset, count)
        return parse_memory_dump(self._command_expect_prompt_or_error(f"dumpimem {offset} {count}", timeout=60.0))

    def dump_dmem_ascii(self, count: int, offset: int = 0) -> dict[int, str]:
        _check_span(offset, count)
        return parse_memory_dump(self._command_expect_prompt_or_error(f"dumpdmem {offset} {count}", timeout=60.0))

    def load_imem_bin(self, words: Iterable[int | str], offset: int = 0) -> str:
        return self._load_binary("loadimem_bin", "READY_IMEM_BIN", "IMEM_LOAD_COMPLETE", words, offset)

    def load_dmem_bin(self, words: Iterable[int | str], offset: int = 0) -> str:
        return self._load_binary("loaddmem_bin", "READY_DMEM_BIN", "DMEM_LOAD_COMPLETE", words, offset)

    def _load_binary(self, cmd: str, ready: str, complete: str,
                     words: Iterable[int | str], offset: int) -> str:
        normalized = [normalize_word(w) for w in words]
        _check_span(offset, len(normalized))
        self.write_line(f"{cmd} {offset} {len(normalized)}")
        first, marker = self.read_until([ready, "ERROR"], timeout=5.0)
        if marker == "ERROR":
            raise RuntimeError(f"Binary load rejected:\n{first + self.wait_prompt()}")
        payload = words_to_le_bytes(normalized)
        if self.verbose:
            print(f"[INFO] Sending {len(payload)} raw bytes")
        self.ser.write(payload)
        self.ser.flush()
        second, marker = self.read_until([complete, "ERROR"], timeout=60.0)
        if marker == "ERROR":
            raise RuntimeError(f"Binary load failed:\n{first + second + self.wait_prompt()}")
        return first + second + self.wait_prompt(timeout=10.0)

    def dump_dmem_bin(self, count: int, offset: int = 0) -> dict[int, str]:
        _check_span(offset, count)
        self.write_line(f"dumpdmem_bin {offset} {count}")
        output, marker = self.read_until_bytes([b"BEGIN_DMEM_BIN\n", b"ERROR"], timeout=5.0)
        if marker == b"ERROR":
            raise RuntimeError(f"Binary dump rejected:\n{output.decode('ascii', errors='replace') + self.wait_prompt()}")
        payload = self.read_exact(count * 4, timeout=60.0)
        result = {offset + i: f"{struct.unpack_from('<I', payload, 4 * i)[0]:08x}"
                  for i in range(count)}
        self.wait_prompt(timeout=10.0)
        return result

    # Names used by existing demo scripts.
    def load_imem(self, words: Iterable[int | str], offset: int = 0) -> str:
        return self.load_imem_bin(words, offset=offset)

    def load_dmem(self, words: Iterable[int | str], offset: int = 0) -> str:
        return self.load_dmem_bin(words, offset=offset)

    def dump_dmem(self, count: int, offset: int = 0) -> dict[int, str]:
        return self.dump_dmem_bin(count=count, offset=offset)


GpgpuUart = GpgpuUartMonitor
