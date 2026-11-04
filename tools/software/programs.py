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


def _binutil_for(compiler: str, tool: str) -> str:
    path = Path(compiler)
    if not path.name.endswith("-gcc"):
        raise ValueError(
            f"tools.riscv_gcc.command must end in '-gcc' so {tool} can be derived"
        )
    return str(path.with_name(f"{path.name[:-3]}{tool}"))


def _objdump_for(compiler: str) -> str:
    return _binutil_for(compiler, "objdump")


def _elf_path(artifact_directory: Path, program: str) -> Path:
    return artifact_directory / f"{program}.elf"


def _memory_path(artifact_directory: Path, program: str) -> Path:
    return artifact_directory / f"{program}_instructions.mem"


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
    """Extract instruction mnemonics and operands from an objdump listing."""

    output.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for line in disassembly.read_text(encoding="utf-8").splitlines():
        fields = _instruction_fields(line)
        if fields is not None:
            lines.append(fields[1])
    output.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")


def write_instruction_memory(disassembly: Path, output: Path) -> None:
    """Extract 32-bit instruction words from an objdump listing."""

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
    elf = _elf_path(artifact_directory, program)
    link_map = artifact_directory / f"{program}.map"
    dump = artifact_directory / f"{program}_dump_real.asm"
    assembly = artifact_directory / f"{program}_program.asm"
    memory = _memory_path(artifact_directory, program)

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


# Linker symbols bounding GPGPU_ARGS (gpgpu.ld): the host writes the arguments there.
_ARGS_BASE_SYMBOL = "__gpu_args_base"
_ARGS_END_SYMBOL = "__gpu_args_end"
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def autorun_settings(config: ResolvedConfig, program_names: list[str]) -> dict[str, Any]:
    """Validated software.host.autorun values (and the define prefix they use)."""

    header = config.get("software.host.autorun.header")
    if not isinstance(header, str) or not header.endswith(".h"):
        raise ValueError("software.host.autorun.header must be a repository-relative .h path")
    enabled = config.get("software.host.autorun.enabled")
    if not isinstance(enabled, bool):
        raise ValueError("software.host.autorun.enabled must be true or false")
    program = config.get("software.host.autorun.program")
    if not isinstance(program, str) or (enabled and program not in program_names):
        raise ValueError(
            f"software.host.autorun.program must be one of: {', '.join(program_names)}"
        )
    args = config.get("software.host.autorun.args")
    if not isinstance(args, (list, tuple)) or not all(
        (isinstance(arg, int) and not isinstance(arg, bool) and 0 <= arg <= 0xFFFFFFFF)
        or (isinstance(arg, str) and _IDENTIFIER.fullmatch(arg))
        for arg in args
    ):
        raise ValueError(
            "software.host.autorun.args must list 32-bit unsigned integers or C names "
            "such as GPGPU_FB0_BASE"
        )
    display = config.get("software.host.autorun.display")
    if isinstance(display, bool) or not isinstance(display, int) or display < 0:
        raise ValueError("software.host.autorun.display must be a framebuffer index")
    prefix = config.get("software.host.define_prefix")
    if not isinstance(prefix, str) or not _IDENTIFIER.fullmatch(prefix):
        raise ValueError("software.host.define_prefix must be an identifier")
    return {"header": header, "enabled": enabled, "program": program, "args": list(args),
            "display": display, "define_prefix": prefix}


def read_args_window(nm_command: list[str]) -> tuple[int, int]:
    """(first DMEM word, word count) of GPGPU_ARGS from the program's ELF symbols."""

    symbols = {}
    listing = subprocess.run(nm_command, check=True, capture_output=True, text=True).stdout
    for line in listing.splitlines():
        fields = line.split()
        if len(fields) == 3 and fields[2] in (_ARGS_BASE_SYMBOL, _ARGS_END_SYMBOL):
            symbols[fields[2]] = int(fields[0], 16)
    missing = [name for name in (_ARGS_BASE_SYMBOL, _ARGS_END_SYMBOL) if name not in symbols]
    if missing:
        raise ValueError(f"{' '.join(nm_command)}: no symbol {', '.join(missing)}")
    base, end = symbols[_ARGS_BASE_SYMBOL], symbols[_ARGS_END_SYMBOL]
    if base % 4 or end % 4 or end <= base:
        raise ValueError(f"GPGPU_ARGS window 0x{base:x}..0x{end:x} is not whole words")
    return base // 4, (end - base) // 4


def render_autorun_header(settings: dict[str, Any], image: list[int] | None,
                          args_window: tuple[int, int] | None, guard: str) -> str:
    """The C header for the autorun settings; *image* is None when it is disabled."""

    lines = [
        "/* Generated by tools/software/programs.py (task software:host:autorun)",
        " * from software.host.autorun and the program's RISC-V build.",
        " * Do not edit: change the configuration and regenerate.",
        " */",
        f"#ifndef {guard}",
        f"#define {guard}",
        "",
    ]

    def define(name: str, value: str) -> None:
        lines.append(f"#define {settings['define_prefix']}{name:<28} {value}")

    lines.append("/* Program run from boot until a UART key press (software.host.autorun). */")
    if image is None or args_window is None:
        define("AUTORUN", "0")
    else:
        args_word, args_words = args_window
        args = settings["args"]
        if len(args) > args_words:
            raise ValueError(
                f"software.host.autorun.args has {len(args)} values; "
                f"GPGPU_ARGS holds {args_words} words"
            )
        values = [f"0x{arg:08X}U" if isinstance(arg, int) else arg for arg in args]
        values += ["0x00000000U"] * (args_words - len(values))
        define("AUTORUN", "1")
        define("AUTORUN_PROGRAM", f"\"{settings['program']}\"")
        lines.append("/* First DMEM word of GPGPU_ARGS (__gpu_args_base in gpgpu.ld). */")
        define("AUTORUN_ARGS_WORD", f"{args_word}U")
        lines.append("/* Framebuffer shown while it runs (software.host.autorun.display). */")
        define("AUTORUN_DISPLAY", f"{settings['display']}U")
        lines += ["", "/* IMEM image, from word 0. */", "static const u32 gpgpu_autorun_image[] = {"]
        lines += [f"    {', '.join(f'0x{word:08X}U' for word in image[i:i + 6])},"
                  for i in range(0, len(image), 6)]
        lines += ["};", "",
                  "/* GPGPU_ARGS words (software.host.autorun.args; the rest are 0). */",
                  f"static const u32 gpgpu_autorun_args[] = {{ {', '.join(values)} }};"]
    lines += ["", f"#endif /* {guard} */", ""]
    return "\n".join(lines)


def write_autorun_header(settings: dict[str, Any], nm_command: list[str] | None,
                         memory: Path | None, output: Path) -> None:
    image = args_window = None
    if settings["enabled"] and nm_command is not None and memory is not None:
        image = [int(line, 16) for line in memory.read_text(encoding="utf-8").split()]
        args_window = read_args_window(nm_command)
    guard = re.sub(r"\W", "_", output.name).upper()
    output.write_text(render_autorun_header(settings, image, args_window, guard), encoding="utf-8")


def _autorun_task(config: ResolvedConfig, program_names: list[str]) -> dict[str, Any]:
    settings = autorun_settings(config, program_names)
    output = config.repo_root / settings["header"]
    program = settings["program"]
    task: dict[str, Any] = {
        "name": "software:host:autorun",
        "targets": [str(output)],
        "uptodate": [config_changed(settings)],
    }
    if not settings["enabled"]:
        task["actions"] = [(write_autorun_header, [settings, None, None, output])]
        task["file_dep"] = [str(Path(__file__).resolve())]
        return task

    artifact_directory = ProjectPaths.from_config(config).program_builds / program
    elf = _elf_path(artifact_directory, program)
    memory = _memory_path(artifact_directory, program)
    riscv_cc = config.get("tools.riscv_gcc.command")
    if not isinstance(riscv_cc, str):
        raise TypeError("tools.riscv_gcc.command must be a string")
    nm_command = [_binutil_for(riscv_cc, "nm"), str(elf)]
    task["actions"] = [(write_autorun_header, [settings, nm_command, memory, output])]
    task["file_dep"] = [str(elf), str(memory), str(Path(__file__).resolve())]
    task["task_dep"] = [f"software:programs:{program}:mem"]
    return task


def create_tasks(config: ResolvedConfig) -> list[dict[str, Any]]:
    """Create pydoit task dictionaries for every valid program directory."""

    programs_root = _programs_root(config)
    program_names = _program_names(programs_root)
    tasks: list[dict[str, Any]] = []
    for program in program_names:
        tasks.extend(_program_tasks(config, program))
    tasks.append(_autorun_task(config, program_names))
    return tasks
