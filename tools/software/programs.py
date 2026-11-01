"""pydoit task definitions for programs under ``software/programs``.

This module preserves the compiler flags, artifacts, and dependency graph from
the legacy Makefile while exposing them through pydoit's Python API.
"""

from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess
from typing import TYPE_CHECKING, Any

from doit.tools import config_changed
from src.project_paths import ProjectPaths

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


def _run_command(command: list[str], output_directory: Path | None = None) -> None:
    if output_directory is not None:
        output_directory.mkdir(parents=True, exist_ok=True)
    subprocess.run(command, check=True)


def clean_program_artifacts(build_root: Path, artifact_directory: Path) -> None:
    """Remove one program build directory without following build-tree symlinks."""

    root = build_root.resolve()
    candidate = artifact_directory.absolute()
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise RuntimeError(f"Refusing to clean outside build root: {candidate}") from exc
    if not relative.parts:
        raise RuntimeError("Refusing to clean the build root itself")

    current = root
    for component in relative.parts:
        current /= component
        if current.is_symlink():
            raise RuntimeError(f"Refusing to clean through symbolic link: {current}")

    if candidate.exists():
        shutil.rmtree(candidate)


def _positive_int(config: ResolvedConfig, key: str) -> int:
    value = config.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{key} must be a positive integer")
    return value


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

    output.parent.mkdir(parents=True, exist_ok=True)
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
    """Extract all instruction mnemonics and operands from an objdump listing.

    RET and ECALL are instructions, not image boundaries: linked callees may
    follow either instruction in address order and must remain in the image.
    """

    output.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for line in disassembly.read_text(encoding="utf-8").splitlines():
        fields = _instruction_fields(line)
        if fields is not None:
            lines.append(fields[1])
    output.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")


def write_instruction_memory(disassembly: Path, output: Path) -> None:
    """Extract every 32-bit instruction word, including code after RET/ECALL."""

    output.parent.mkdir(parents=True, exist_ok=True)
    words = []
    for line in disassembly.read_text(encoding="utf-8").splitlines():
        fields = _instruction_fields(line)
        if fields is not None and len(fields[0]) == 8:
            words.append(fields[0])
    output.write_text("".join(f"{word}\n" for word in words), encoding="utf-8")


def _programs_root(config: ResolvedConfig) -> Path:
    return ProjectPaths.from_config(config).software_programs


def _program_names(programs_root: Path) -> list[str]:
    return sorted(
        path.name
        for path in programs_root.iterdir()
        if path.is_dir() and (path / f"{path.name}.c").is_file()
    )


def _program_tasks(config: ResolvedConfig, program: str) -> list[dict[str, Any]]:
    paths = ProjectPaths.from_config(config)
    programs_root = paths.software_programs
    directory = programs_root / program
    artifact_directory = paths.program_builds / program
    source = directory / f"{program}.c"
    linker_script = programs_root / "gpgpu.ld"
    header_dependencies = sorted(
        {
            *programs_root.glob("*.h"),
            *directory.glob("*.h"),
        }
    )

    native_executable = artifact_directory / f"{program}_x86"
    elf = artifact_directory / f"{program}.elf"
    link_map = artifact_directory / f"{program}.map"
    dump = artifact_directory / f"{program}_dump_real.asm"
    assembly = artifact_directory / f"{program}_program.asm"
    memory = artifact_directory / f"{program}_instructions.mem"

    native_cc = config.get("tools.native_cc.command")
    riscv_cc = config.get("tools.riscv_gcc.command")
    march = config.get("software.riscv.march")
    abi = config.get("software.riscv.abi")
    num_cores = _positive_int(config, "architecture.num_cores")
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

    core_define = f"-DGPGPU_NUM_CORES={num_cores}"
    native_command = [
        native_cc,
        "-O2",
        core_define,
        "-o",
        str(native_executable),
        str(source),
    ]
    elf_command = [
        riscv_cc,
        "-O2",
        f"-march={march}",
        f"-mabi={abi}",
        core_define,
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
            "name": f"{prefix}:clean",
            "actions": [(clean_program_artifacts, [paths.build_root, artifact_directory])],
            "uptodate": [False],
        },
        {
            "name": x86_build_name,
            "actions": [(_run_command, [native_command, artifact_directory])],
            "file_dep": [str(source), *(str(path) for path in header_dependencies)],
            "targets": [str(native_executable)],
            "uptodate": [config_changed({"num_cores": num_cores})],
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
            "actions": [(_run_command, [elf_command, artifact_directory])],
            "file_dep": [
                str(source),
                str(linker_script),
                *(str(path) for path in header_dependencies),
            ],
            "targets": [str(elf), str(link_map)],
            "uptodate": [config_changed({"num_cores": num_cores})],
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
