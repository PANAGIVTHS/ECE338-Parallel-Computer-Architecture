"""What the host loads besides IMEM: a program's GMEM data image and its memory layout.

Both come from the linked ELF (software/programs/linker.ld):

  <program>_gmem.mem     .rodata and .data as '<byte address> <word>' hex pairs, the
                         format of the RTL cases' ddr_seed.mem
  <program>_layout.json  GPGPU_ARGS, .shared, the stacks, .bss and every data symbol,
                         for the loaders and the FPGA adapters

The linker layout every program links against (linker_layout.ld) is written here too.
"""
from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any, NamedTuple

_SHT_SYMTAB, _SHT_NOBITS = 2, 8
_STT_OBJECT, _STT_FUNC, _STT_NOTYPE = 1, 2, 0


class ElfSection(NamedTuple):
    name: str
    type: int
    address: int
    offset: int
    size: int
    link: int
    entry_size: int
    flags: int = 0


class ElfSymbol(NamedTuple):
    name: str
    value: int
    size: int
    kind: int
    section: int


def _sections(data: bytes) -> list[ElfSection]:
    if data[:4] != b"\x7fELF" or data[4] != 1 or data[5] != 1:
        raise ValueError("not a little-endian ELF32 file")
    shoff, = struct.unpack_from("<I", data, 0x20)
    shentsize, shnum, shstrndx = struct.unpack_from("<HHH", data, 0x2E)
    raw = [struct.unpack_from("<IIIIIIIIII", data, shoff + i * shentsize) for i in range(shnum)]
    names = raw[shstrndx]

    def name(offset: int) -> str:
        start = names[4] + offset
        return data[start:data.index(b"\0", start)].decode()

    return [ElfSection(name(r[0]), r[1], r[3], r[4], r[5], r[6], r[9], r[2]) for r in raw]


def _symbols(data: bytes, sections: list[ElfSection]) -> list[ElfSymbol]:
    symtab = next((s for s in sections if s.type == _SHT_SYMTAB), None)
    if symtab is None:
        return []
    strtab = sections[symtab.link]
    result = []
    for index in range(symtab.size // symtab.entry_size):
        name_offset, value, size, info, _, shndx = struct.unpack_from("<IIIBBH", data, symtab.offset + index * symtab.entry_size)
        start = strtab.offset + name_offset
        name = data[start:data.index(b"\0", start)].decode()
        if name:
            result.append(ElfSymbol(name, value, size, info & 0xF, shndx))
    return result


def _image_words(data: bytes, sections: list[ElfSection], names: tuple[str, ...]) -> dict[int, int]:
    """{byte address: word} of the loadable sections, little-endian, zero-padded to whole words."""
    words: dict[int, int] = {}
    for section in sections:
        if section.name not in names or section.type == _SHT_NOBITS or section.size == 0:
            continue
        if section.address % 4:
            raise ValueError(f"{section.name} at 0x{section.address:08x} is not word-aligned")
        contents = data[section.offset:section.offset + section.size]
        contents += b"\0" * (-len(contents) % 4)
        for index in range(0, len(contents), 4):
            words[section.address + index], = struct.unpack_from("<I", contents, index)
    return words


def write_program_files(elf: Path, gmem_image: Path, layout: Path, program: str) -> None:
    data = elf.read_bytes()
    sections = _sections(data)
    symbols = _symbols(data, sections)
    absolute = {symbol.name: symbol.value for symbol in symbols}
    required = ("__gpu_args_base", "__gpu_args_end", "__shared_start", "__shared_end", "__gpu_stack_bottom",
                "__stack_top", "__gmem_data_start", "__bss_start", "__bss_end", "__gmem_data_end",
                "__gmem_free_base", "__gmem_free_end")
    missing = [name for name in required if name not in absolute]
    if missing:
        raise ValueError(f"{elf}: linker symbols missing ({', '.join(missing)}): not linked with linker.ld")

    image = _image_words(data, sections, (".rodata", ".data"))
    lines = [f"// {program}: .rodata and .data, '<byte address> <word>' (GMEM image, written once per program load)"]
    lines += [f"{address:08x} {word:08x}" for address, word in sorted(image.items())]
    gmem_image.write_text("\n".join(lines) + "\n", encoding="utf-8")

    by_index = dict(enumerate(sections))
    objects = {symbol.name: {"address": symbol.value, "size": symbol.size, "section": by_index[symbol.section].name}
               for symbol in symbols if symbol.kind == _STT_OBJECT and symbol.section in by_index}

    def region(start: str, end: str) -> dict[str, int]:
        return {"start": absolute[start], "end": absolute[end]}

    description: dict[str, Any] = {
        "program": program,
        "args": {"base": absolute["__gpu_args_base"],
                 "words": (absolute["__gpu_args_end"] - absolute["__gpu_args_base"]) // 4},
        "shared": region("__shared_start", "__shared_end"),
        "stack": region("__gpu_stack_bottom", "__stack_top"),
        "gmem_data": region("__gmem_data_start", "__gmem_data_end"),
        "bss": region("__bss_start", "__bss_end"),
        "gmem_free": region("__gmem_free_base", "__gmem_free_end"),
        "gmem_image": gmem_image.name,
        "gmem_image_words": len(image),
        "symbols": dict(sorted(objects.items())),
    }
    layout.write_text(json.dumps(description, indent=2) + "\n", encoding="utf-8")


def write_linker_layout(settings: dict[str, int], constants_file: Path, output: Path) -> None:
    """MEMORY regions and ABI sizes: architecture.memory, and the RTL's memory map as elaborated."""
    constants = {}
    for line in constants_file.read_text(encoding="utf-8").splitlines():
        name, _, value = line.partition("=")
        constants[name] = int(value)
    rtl = {name: constants[f"gpu_pkg::{name}"] for name in ("IMEM_ENTRIES", "DMEM_ENTRIES", "DMEM_BASE", "GMEM_BASE", "GMEM_SIZE")}
    imem, dmem = 4 * rtl["IMEM_ENTRIES"], 4 * rtl["DMEM_ENTRIES"]
    if (imem, dmem) != (settings["imem_bytes"], settings["dmem_bytes"]):
        raise ValueError(f"the RTL has IMEM {imem} B and DMEM {dmem} B, architecture.memory "
                         f"{settings['imem_bytes']} B and {settings['dmem_bytes']} B: run `gpgpu rtl config`")
    if settings["gmem_data_bytes"] >= rtl["GMEM_SIZE"]:
        raise ValueError(f"architecture.memory.gmem_data_bytes must be less than GMEM_SIZE (0x{rtl['GMEM_SIZE']:x})")
    data_end = rtl["GMEM_BASE"] + settings["gmem_data_bytes"]
    free = rtl["GMEM_BASE"] + rtl["GMEM_SIZE"] - data_end
    text = "\n".join([
        "/* Generated by `gpgpu software programs:layout` from architecture.memory and the",
        " * RTL's memory map (gpu_pkg). Do not edit; linker.ld includes it. */",
        "MEMORY",
        "{",
        f"    IMEM  (rx) : ORIGIN = 0x{0:08X}, LENGTH = 0x{imem:X}",
        f"    DMEM  (rw) : ORIGIN = 0x{rtl['DMEM_BASE']:08X}, LENGTH = 0x{dmem:X}",
        f"    GDATA (rw) : ORIGIN = 0x{rtl['GMEM_BASE']:08X}, LENGTH = 0x{settings['gmem_data_bytes']:X}",
        f"    GFREE (rw) : ORIGIN = 0x{data_end:08X}, LENGTH = 0x{free:X}",
        "}",
        "",
        f"__gpu_num_cores    = {settings['num_cores']};",
        f"__gpu_args_words   = {settings['args_words']};",
        f"__gpu_stack_stride = {settings['stack_bytes_per_lane']};",
        ""])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
