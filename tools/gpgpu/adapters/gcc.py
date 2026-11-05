"""Toolchain on GCC: native and RISC-V builds of software/programs, and the host headers."""
from __future__ import annotations

import re
import shutil
import subprocess
from functools import partial
from pathlib import Path

from gpgpu.api import GpgpuError, Step

from . import host_headers
from .config import Config, Section
from .design import architecture, program_names, program_output
from .tools import run

_RISCV_CFLAGS = ("-ffreestanding", "-fno-builtin", "-fomit-frame-pointer", "-ffixed-x31", "-ffunction-sections",
                 "-fdata-sections", "-msmall-data-limit=0", "-mno-relax")
_INSTRUCTION = re.compile(r"^\s*[0-9a-fA-F]+:\s+(\S+)(?:\s+(.*))?$")


class _Riscv(Section):
    march: str
    abi: str


def _instructions(listing: Path) -> list[tuple[str, str]]:
    """(hex code, assembly) of each instruction line in an objdump listing."""
    matches = map(_INSTRUCTION.match, listing.read_text(encoding="utf-8").splitlines())
    return [(match[1], match[2] or "") for match in matches if match]


def _write_disassembly(command: list[str], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as stream:
        subprocess.run(command, check=True, stdout=stream)
    mnemonics = sorted({assembly.split(maxsplit=1)[0] for _, assembly in _instructions(output) if assembly})
    print("---------------------------------------------------")
    print("Instruction Set used in program (RISC-V):")
    print(" ".join(mnemonics))
    print("---------------------------------------------------")


def _write_assembly(listing: Path, output: Path) -> None:
    output.write_text("".join(f"{assembly}\n" for _, assembly in _instructions(listing)), encoding="utf-8")


def _write_memory(listing: Path, output: Path) -> None:
    output.write_text("".join(f"{code}\n" for code, _ in _instructions(listing) if len(code) == 8), encoding="utf-8")


def _remove(directory: Path) -> None:
    if directory.exists():
        shutil.rmtree(directory)


class GccToolchain:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._root = config.repo_root / "software/programs"
        self._cores = architecture(config).num_cores
        self._riscv = config.section("software.riscv", _Riscv)
        self._native_cc, self._riscv_cc = config.tool("native_cc"), config.tool("riscv_gcc")
        if not self._riscv_cc.endswith("-gcc"):
            raise GpgpuError("tools.riscv_gcc.command must end in '-gcc', so objdump and nm can be derived from it")

    def _binutil(self, tool: str) -> str:
        return f"{self._riscv_cc[:-3]}{tool}"

    def _out(self, program: str, suffix: str) -> Path:
        return program_output(self._config, program, suffix)

    def _sources(self, program: str) -> tuple[Path, list[Path]]:
        directory = self._root / program
        return directory / f"{program}.c", sorted({*self._root.glob("*.h"), *directory.glob("*.h")})

    def programs(self) -> list[str]:
        return program_names(self._config)

    def clean(self, program: str) -> Step:
        return Step(partial(_remove, self._out(program, "").parent), always_run=True)

    def build_native(self, program: str) -> Step:
        source, headers = self._sources(program)
        executable = self._out(program, "_x86")
        command = [self._native_cc, "-O2", f"-DGPGPU_NUM_CORES={self._cores}", "-o", str(executable), str(source)]
        return Step(partial(run, command, creates=executable.parent), inputs=(source, *headers), outputs=(executable,),
                    fingerprint={"num_cores": self._cores})

    def run_native(self, program: str) -> Step:
        return Step(partial(run, [str(self._out(program, "_x86"))]), always_run=True)

    def build_elf(self, program: str) -> Step:
        source, headers = self._sources(program)
        elf, link_map = self._out(program, ".elf"), self._out(program, ".map")
        linker_script = self._root / "gpgpu.ld"
        command = [self._riscv_cc, "-O2", f"-march={self._riscv.march}", f"-mabi={self._riscv.abi}",
                   f"-DGPGPU_NUM_CORES={self._cores}", *_RISCV_CFLAGS, "-o", str(elf), str(source), "-nostdlib", "-nostartfiles",
                   f"-Wl,-T,{linker_script}", f"-Wl,-Map,{link_map}", "-Wl,--build-id=none"]
        return Step(partial(run, command, creates=elf.parent), inputs=(source, linker_script, *headers),
                    outputs=(elf, link_map), fingerprint={"num_cores": self._cores})

    def disassemble(self, program: str) -> Step:
        elf, listing = self._out(program, ".elf"), self._out(program, "_dump_real.asm")
        command = [self._binutil("objdump"), "-d", "-M", "no-aliases,numeric", str(elf)]
        return Step(partial(_write_disassembly, command, listing), inputs=(elf,), outputs=(listing,))

    def assembly(self, program: str) -> Step:
        listing, output = self._out(program, "_dump_real.asm"), self._out(program, "_program.asm")
        return Step(partial(_write_assembly, listing, output), inputs=(listing,), outputs=(output,))

    def memory_image(self, program: str) -> Step:
        listing, output = self._out(program, "_dump_real.asm"), self._out(program, "_instructions.mem")
        return Step(partial(_write_memory, listing, output), inputs=(listing,), outputs=(output,))

    def host_platform_header(self) -> Step:
        return host_headers.platform_step(self._config)

    def host_autorun_header(self) -> Step:
        return host_headers.autorun_step(self._config, self._binutil("nm"))

    def autorun_program(self) -> str | None:
        return host_headers.autorun_program(self._config)
