"""pydoit task definitions for programs under ``software/programs``.

This module preserves the compiler flags, artifacts, and dependency graph from
the legacy Makefile while exposing them through pydoit's Python API.
"""

from __future__ import annotations

from pathlib import Path
import re
import subprocess
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from config import ResolvedConfig


_RISCV_CFLAGS = (
    "-O2",
    "-ffreestanding",
    "-fno-builtin",
    "-fomit-frame-pointer",
    "-ffixed-x31",
    "-ffunction-sections",
    "-fdata-sections",
    "-msmall-data-limit=0",
    "-mno-relax",
)
_RISCV_LDFLAGS = (
    "-nostdlib",
    "-nostartfiles",
    "-Wl,--build-id=none",
)
_INSTRUCTION_LINE = re.compile(r"^\s*[0-9a-fA-F]+:\s+(\S+)(?:\s+(.*))?$")


def _run_command(command: list[str]) -> None:
    subprocess.run(command, check=True)


def _objdump_for(compiler: str) -> str:
    path = Path(compiler)
    if not path.name.endswith("-gcc"):
        raise ValueError(
            "tools.riscv_gcc.command must end in '-gcc' so objdump can be derived"
        )
    return str(path.with_name(f"{path.name[:-3]}objdump"))


def _instruction_fields(line: str) -> tuple[str, str] | None:
    match = _INSTRUCTION_LINE.match(line)
    if match is None:
        return None
    hex_code, assembly = match.groups()
    return hex_code, assembly or ""


def write_disassembly(command: list[str], output: Path) -> None:
    """Run objdump and write its complete disassembly to *output*."""

    with output.open("w", encoding="utf-8") as stream:
        subprocess.run(command, check=True, stdout=stream)

    instructions = sorted(
        {
            assembly.split(maxsplit=1)[0]
            for line in output.read_text(encoding="utf-8").splitlines()
            if (fields := _instruction_fields(line)) is not None
            and (assembly := fields[1])
        }
    )
    print("---------------------------------------------------")
    print("Instruction Set used in program (RISC-V):")
    print(" ".join(instructions))
    print("---------------------------------------------------")


def write_program_assembly(disassembly: Path, output: Path) -> None:
    """Extract instruction mnemonics and operands from an objdump listing."""

    lines = []
    for line in disassembly.read_text(encoding="utf-8").splitlines():
        fields = _instruction_fields(line)
        if fields is not None:
            lines.append(fields[1])
    output.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")


def write_instruction_memory(disassembly: Path, output: Path) -> None:
    """Extract 32-bit instruction words from an objdump listing."""

    words = []
    for line in disassembly.read_text(encoding="utf-8").splitlines():
        fields = _instruction_fields(line)
        if fields is not None and len(fields[0]) == 8:
            words.append(fields[0])
    output.write_text("".join(f"{word}\n" for word in words), encoding="utf-8")


def _programs_root(config: ResolvedConfig) -> Path:
    software_root = config.repo_path("paths.software.root")
    programs_component = config.get("paths.software.programs")
    if not isinstance(programs_component, str):
        raise TypeError("paths.software.programs must be a string")
    return software_root / programs_component


def _program_names(programs_root: Path) -> list[str]:
    return sorted(
        path.name
        for path in programs_root.iterdir()
        if path.is_dir() and (path / f"{path.name}.c").is_file()
    )


def _program_tasks(config: ResolvedConfig, program: str) -> list[dict[str, Any]]:
    programs_root = _programs_root(config)
    directory = programs_root / program
    source = directory / f"{program}.c"
    linker_script = programs_root / "gpgpu.ld"

    native_executable = directory / f"{program}_x86"
    elf = directory / f"{program}.elf"
    link_map = directory / f"{program}.map"
    dump = directory / f"{program}_dump_real.asm"
    assembly = directory / f"{program}_program.asm"
    memory = directory / f"{program}_instructions.mem"

    native_cc = config.get("tools.native_cc.command")
    riscv_cc = config.get("tools.riscv_gcc.command")
    march = config.get("software.riscv.march")
    abi = config.get("software.riscv.abi")
    for key, value in (
        ("tools.native_cc.command", native_cc),
        ("tools.riscv_gcc.command", riscv_cc),
        ("software.riscv.march", march),
        ("software.riscv.abi", abi),
    ):
        if not isinstance(value, str):
            raise TypeError(f"{key} must be a string")

    objdump = _objdump_for(riscv_cc)
    prefix = f"software:programs:{program}"
    x86_build_name = f"{prefix}:x86:build"
    x86_name = f"{prefix}:x86"
    elf_name = f"{prefix}:elf"
    dump_name = f"{prefix}:dump"
    assembly_name = f"{prefix}:assembly"
    mem_name = f"{prefix}:mem"
    riscv_build_name = f"{prefix}:riscv:build"

    native_command = [native_cc, "-O2", "-o", str(native_executable), str(source)]
    elf_command = [
        riscv_cc,
        "-O2",
        f"-march={march}",
        f"-mabi={abi}",
        *_RISCV_CFLAGS[1:],
        "-o",
        str(elf),
        str(source),
        *_RISCV_LDFLAGS[:2],
        f"-Wl,-T,{linker_script}",
        f"-Wl,-Map,{link_map}",
        _RISCV_LDFLAGS[2],
    ]
    dump_command = [objdump, "-d", "-M", "no-aliases,numeric", str(elf)]

    return [
        {
            "name": x86_build_name,
            "actions": [(_run_command, [native_command])],
            "file_dep": [str(source)],
            "targets": [str(native_executable)],
            "clean": True,
        },
        {
            "name": x86_name,
            "actions": [(_run_command, [[str(native_executable)]])],
            "task_dep": [x86_build_name],
            "uptodate": [False],
        },
        {
            "name": elf_name,
            "actions": [(_run_command, [elf_command])],
            "file_dep": [str(source), str(linker_script)],
            "targets": [str(elf), str(link_map)],
            "clean": True,
        },
        {
            "name": dump_name,
            "actions": [(write_disassembly, [dump_command, dump])],
            "file_dep": [str(elf)],
            "task_dep": [elf_name],
            "targets": [str(dump)],
            "clean": True,
        },
        {
            "name": assembly_name,
            "actions": [(write_program_assembly, [dump, assembly])],
            "file_dep": [str(dump)],
            "task_dep": [dump_name],
            "targets": [str(assembly)],
            "clean": True,
        },
        {
            "name": mem_name,
            "actions": [(write_instruction_memory, [dump, memory])],
            "file_dep": [str(dump)],
            "task_dep": [dump_name],
            "targets": [str(memory)],
            "clean": True,
        },
        {
            "name": riscv_build_name,
            "actions": None,
            "task_dep": [assembly_name],
        },
        {
            "name": f"{prefix}:all",
            "actions": None,
            "task_dep": [riscv_build_name, x86_build_name],
        },
    ]


def create_tasks(config: ResolvedConfig) -> list[dict[str, Any]]:
    """Create pydoit task dictionaries for every valid program directory."""

    programs_root = _programs_root(config)
    tasks: list[dict[str, Any]] = []
    for program in _program_names(programs_root):
        tasks.extend(_program_tasks(config, program))
    return tasks
