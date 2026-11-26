#!/usr/bin/env python3
"""UART client for the GPGPU AXI4-Lite bare-metal monitor.

The PC still talks to the Zynq over UART. The Zynq application translates
commands to Xil_In32/Xil_Out32 accesses in one GPU AXI aperture; the host-PC
serial protocol is intentionally compatible with the older GPIO-based monitor.
"""

from __future__ import annotations

import re
import struct
import sys
import time
import zlib
from pathlib import Path
from typing import Iterable, cast

try:
    import serial
except ImportError:
    serial = None  # Parsing helpers work without pyserial installed.

RET_INSTR = "00008067"
# Upper bound for IMEM/DMEM word indices: INFO_MEM's 16-bit fields. The real
# sizes come from architecture.memory; the monitor checks them on every command.
DEPTH = 0xFFFF
# GMEM word offsets (from GMEM_BASE): the monitor checks them against GMEM_SIZE.
GMEM_DEPTH = 1 << 24
PROMPT = "gpgpu>"
WORD_BYTES = struct.calcsize("<I")


def normalize_word(word: int | str) -> str:
    """Convert an integer or a hexadecimal string to eight hex digits."""
    value = word if isinstance(word, int) else int(str(word).strip(), 16)
    return f"{value & 0xFFFFFFFF:08x}"


def words_to_le_bytes(words: Iterable[int | str]) -> bytes:
    return b"".join(struct.pack("<I", int(normalize_word(w), 16)) for w in words)


def parse_memory_dump(text: str) -> dict[int, str]:
    """Word index -> word from the monitor's `0xBYTE_ADDRESS: 0xWORD` dump lines."""
    result: dict[int, str] = {}
    for addr, word in re.findall(r"(?m)^\s*0x([0-9a-fA-F]+):\s*0x([0-9a-fA-F]{8})\s*$", text):
        byte_address = int(addr, 16)
        if byte_address % WORD_BYTES:
            raise RuntimeError(f"Memory dump address 0x{byte_address:08x} is not word-aligned")
        result[byte_address // WORD_BYTES] = word.lower()
    return result


def parse_single_word(text: str, mem_name: str, addr: int) -> str:
    pattern = rf"{re.escape(mem_name)}\[{addr}\]\s*=\s*0x([0-9a-fA-F]{{8}})"
    match = re.search(pattern, text)
    if not match:
        raise RuntimeError(f"Could not parse {mem_name}[{addr}] from UART output:\n{text}")
    return match.group(1).lower()


def parse_status(text: str) -> dict[str, int | str]:
    """MMIO status fields: IDLE/RUNNING/STOPPED/FAULTED, IRQ enable/pending and the fault report."""
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
    for field in ("idle", "running", "stopped", "faulted", "irq_enabled", "irq_pending"):
        match = re.search(rf"\b{field}\s*=\s*([01])", text)
        if match:
            status[field] = int(match.group(1))
    for field in ("FAULT_INFO", "FAULT_LANES", "FAULT_PC"):
        match = re.search(rf"(?m)^{field}\s*=\s*0x([0-9a-fA-F]+)", text)
        if match:
            status[field.lower()] = int(match.group(1), 16)
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


def read_gmem_image(path: str | Path) -> dict[int, str]:
    """A program's <program>_gmem.mem: {byte address: word} of its .rodata and .data."""
    words: dict[int, str] = {}
    for line in Path(path).read_text().splitlines():
        fields = line.split("//", 1)[0].split()
        if fields:
            words[int(fields[0], 16)] = normalize_word(fields[1])
    return words


def gmem_runs(image: dict[int, str], gmem_base: int) -> list[tuple[int, list[str]]]:
    """Contiguous (word offset from GMEM_BASE, words) runs of a GMEM image."""
    runs: list[tuple[int, list[str]]] = []
    for address in sorted(image):
        offset = (address - gmem_base) // 4
        if runs and runs[-1][0] + len(runs[-1][1]) == offset:
            runs[-1][1].append(image[address])
        else:
            runs.append((offset, [image[address]]))
    return runs


def load_program_data(monitor: "GpgpuUartMonitor", layout: dict, image: dict[int, str],
                      verify: bool = True) -> None:
    """What a program needs besides IMEM, once per program load (linker.ld):
    .rodata/.data into GMEM, .bss (GMEM) and .shared (DMEM) zeroed.

    `layout` is the program's <program>_layout.json; GPGPU_ARGS are the caller's."""
    gmem_base = layout["gmem_data"]["start"]
    for offset, words in gmem_runs(image, gmem_base):
        monitor.load_gmem_bin(words, offset=offset)
        if verify and monitor.dump_gmem_bin(len(words), offset=offset) != {offset + i: w for i, w in enumerate(words)}:
            raise RuntimeError(f"GMEM readback mismatch at word offset {offset}")
    bss, shared = layout["bss"], layout["shared"]
    monitor.fill_gmem((bss["end"] - bss["start"]) // 4, offset=(bss["start"] - gmem_base) // 4)
    monitor.fill_dmem((shared["end"] - shared["start"]) // 4, offset=shared["start"] // 4)


def elf_load_segments(data: bytes) -> tuple[int, list[tuple[int, bytes]]]:
    """(entry, [(address, bytes)]) of the PT_LOAD segments of a 32-bit little-endian ELF,
    the file bytes only: the program's startup code clears the rest (.bss)."""
    if data[:4] != b"\x7fELF" or data[4] != 1 or data[5] != 1:
        raise ValueError("not a 32-bit little-endian ELF file")
    entry, phoff = struct.unpack_from("<II", data, 0x18)
    phentsize, phnum = struct.unpack_from("<HH", data, 0x2A)
    segments = []
    for index in range(phnum):
        kind, offset, address, _, filesz, _, _, _ = struct.unpack_from("<8I", data, phoff + index * phentsize)
        if kind == 1 and filesz:  # PT_LOAD
            segments.append((address, data[offset:offset + filesz]))
    if not segments:
        raise ValueError("the ELF file has nothing to load")
    return entry, segments


def trim_program_at_ret(words: Iterable[str]) -> list[str]:
    """Legacy helper name: normalize the FULL image without trimming.

    Functions may be linked after either RET or the runtime's ECALL. Neither
    instruction marks the end of an image, so truncation is never safe.
    """
    return [normalize_word(word) for word in words]


def _check_index(index: int) -> None:
    if not 0 <= index < DEPTH:
        raise ValueError(f"GPU memory word index must be 0..{DEPTH - 1}, got {index}")


def _check_span(offset: int, count: int, depth: int = DEPTH) -> None:
    if offset < 0 or count < 0 or offset > depth or count > depth - offset:
        raise ValueError(f"GPU memory range offset={offset}, count={count} exceeds {depth} words")


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

    def load_gmem_bin(self, words: Iterable[int | str], offset: int = 0) -> str:
        """Words into GMEM from word `offset` after GMEM_BASE (the monitor flushes its cache)."""
        return self._load_binary("loadgmem_bin", "READY_GMEM_BIN", "GMEM_LOAD_COMPLETE", words, offset, GMEM_DEPTH)

    def fill_gmem(self, count: int, offset: int = 0, word: int | str = 0) -> str:
        _check_span(offset, count, GMEM_DEPTH)
        return self._fill("fillgmem", count, offset, word)

    def fill_dmem(self, count: int, offset: int = 0, word: int | str = 0) -> str:
        _check_span(offset, count)
        return self._fill("filldmem", count, offset, word)

    def _fill(self, cmd: str, count: int, offset: int, word: int | str) -> str:
        if count == 0:
            return ""
        self.write_line(f"{cmd} {offset} {count} {normalize_word(word)}")
        output, marker = self.read_until(["FILL_COMPLETE", "ERROR"], timeout=60.0)
        if marker == "ERROR":
            raise RuntimeError(f"{cmd} failed:\n{output + self.wait_prompt()}")
        return output + self.wait_prompt(timeout=10.0)

    def _load_binary(self, cmd: str, ready: str, complete: str,
                     words: Iterable[int | str], offset: int, depth: int = DEPTH) -> str:
        normalized = [normalize_word(w) for w in words]
        _check_span(offset, len(normalized), depth)
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

    # ---- Runtime programs (docs/runtime-spec.md, section 9.2) ----

    def load_program(self, entry: int, segments: list[tuple[int, bytes]]) -> str:
        """Send a program to the monitor's loader: each segment with its CRC-32."""
        self.write_line(f"load {entry:x} {len(segments):x}")
        output, marker = self.read_until(["READY_LOAD", "ERROR", "Unknown command"], timeout=10.0)
        if marker == "Unknown command":
            raise RuntimeError("The monitor has no program loader: deploy a monitor built from this branch "
                               "(gpgpu fpga deploy)")
        if marker == "ERROR":
            raise RuntimeError(f"The monitor refused the program:\n{output + self.wait_prompt()}")
        seconds_per_byte = 12.0 / self.ser.baudrate  # 10 bits per byte, and some slack
        for address, data in segments:
            self.ser.write(struct.pack("<III", address, len(data), zlib.crc32(data)))
            self.ser.flush()
            text, marker = self.read_until(["SEGMENT_READY", "ERROR"], timeout=10.0)
            if marker == "ERROR":
                raise RuntimeError(f"The monitor refused a segment:\n{output + text + self.wait_prompt()}")
            self.ser.write(data)
            self.ser.flush()
            text, marker = self.read_until(["SEGMENT_OK", "ERROR"], timeout=10.0 + len(data) * seconds_per_byte)
            if marker == "ERROR":
                raise RuntimeError(f"A segment did not load:\n{output + text + self.wait_prompt()}")
            output += text
        text, marker = self.read_until(["LOAD_COMPLETE", "ERROR"], timeout=10.0)
        if marker == "ERROR":
            raise RuntimeError(f"The program did not load:\n{output + text + self.wait_prompt()}")
        return output + text + self.wait_prompt(timeout=10.0)

    def exec_program(self, arguments: list[str], timeout: float, echo=None) -> int:
        """Run the loaded program, pass its console output to `echo` as it arrives, and
        return its status when it is back in the monitor."""
        if not arguments or any(not argument or re.search(r"\s", argument) for argument in arguments):
            raise ValueError("program arguments must be non-empty and contain no whitespace")
        line = "exec " + " ".join(arguments)
        if len(line) > 120:
            raise ValueError("the program's name and arguments must fit 120 characters (the monitor's line)")
        echo = echo or (lambda text: print(text, end="", flush=True))
        self.write_line(line)
        output, marker = self.read_until(["EXEC_START", "ERROR"], timeout=10.0)
        if marker == "ERROR":
            raise RuntimeError(f"The program did not start:\n{output + self.wait_prompt()}")
        pattern = re.compile(rb"EXEC_RETURN (-?\d+)")
        deadline = time.monotonic() + timeout
        shown = 0
        while True:
            match = pattern.search(self.rx_buffer)
            end = match.end() if match else len(self.rx_buffer)
            if end > shown:
                echo(bytes(self.rx_buffer[shown:end]).decode("ascii", errors="replace"))
                shown = end
            if match:
                status = int(match.group(1))  # before the buffer under the match changes
                del self.rx_buffer[:match.end()]
                break
            if time.monotonic() >= deadline:
                raise TimeoutError(f"The program did not return within {timeout:g} s")
            try:
                self._read_from_serial(timeout=min(1.0, max(0.0, deadline - time.monotonic())))
            except TimeoutError:
                pass
        echo("\n")
        self.wait_prompt(timeout=10.0)
        return status

    def dump_dmem_bin(self, count: int, offset: int = 0) -> dict[int, str]:
        _check_span(offset, count)
        return self._dump_binary("dumpdmem_bin", b"BEGIN_DMEM_BIN\n", count, offset)

    def dump_gmem_bin(self, count: int, offset: int = 0) -> dict[int, str]:
        """{word offset from GMEM_BASE: word} (the monitor invalidates its cache first)."""
        _check_span(offset, count, GMEM_DEPTH)
        return self._dump_binary("dumpgmem_bin", b"BEGIN_GMEM_BIN\n", count, offset)

    def _dump_binary(self, cmd: str, begin: bytes, count: int, offset: int) -> dict[int, str]:
        self.write_line(f"{cmd} {offset} {count}")
        output, marker = self.read_until_bytes([begin, b"ERROR"], timeout=5.0)
        if marker == b"ERROR":
            raise RuntimeError(f"Binary dump rejected:\n{output.decode('ascii', errors='replace') + self.wait_prompt()}")
        payload = self.read_exact(count * 4, timeout=60.0)
        result = {offset + i: f"{struct.unpack_from('<I', payload, 4 * i)[0]:08x}"
                  for i in range(count)}
        self.wait_prompt(timeout=10.0)
        return result


GpgpuUart = GpgpuUartMonitor
