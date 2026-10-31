from __future__ import annotations

from pathlib import Path
import shutil

import pytest
from doit.tools import config_changed
from tools.software import host_platform, programs


class StubResolvedConfig:
    def __init__(self, repo_root: Path, build_root: Path | None = None) -> None:
        self.repo_root = repo_root
        self._build_root = build_root or repo_root / "build"

    def get(self, key: str):
        values = {
            "architecture.num_cores": 8,
            "software.riscv.march": "rv32im",
            "software.riscv.abi": "ilp32",
            "tools.native_cc.command": "gcc",
            "tools.riscv_gcc.command": "/opt/riscv/bin/riscv64-unknown-elf-gcc",
        }
        return values[key]

    @property
    def build_root(self) -> Path:
        return self._build_root


def make_repo(tmp_path: Path, build_root: Path | None = None) -> StubResolvedConfig:
    programs_dir = tmp_path / "software/programs"
    program_dir = programs_dir / "example"
    program_dir.mkdir(parents=True)
    (program_dir / "example.c").write_text("int main(void) { return 0; }\n")
    (programs_dir / "gpgpu.ld").write_text("SECTIONS {}\n")
    (programs_dir / "gpgpu_config.h").write_text("#define GPGPU_NUM_CORES 32u\n")
    (programs_dir / "gpgpu_runtime.h").write_text('#include "gpgpu_config.h"\n')
    return StubResolvedConfig(tmp_path, build_root)


def tasks_by_name(config: StubResolvedConfig) -> dict[str, dict]:
    return {task["name"]: task for task in programs.create_tasks(config)}  # type: ignore[arg-type]


def test_create_tasks_preserves_makefile_build_graph_and_flags(tmp_path: Path) -> None:
    config = make_repo(tmp_path)
    tasks = tasks_by_name(config)
    prefix = "software:programs:example"

    assert set(tasks) == {
        f"{prefix}:clean",
        f"{prefix}:x86:build",
        f"{prefix}:x86",
        f"{prefix}:elf",
        f"{prefix}:dump",
        f"{prefix}:assembly",
        f"{prefix}:mem",
        f"{prefix}:riscv:build",
        f"{prefix}:all",
    }

    x86_command = tasks[f"{prefix}:x86:build"]["actions"][0][1][0]
    assert x86_command == [
        "gcc",
        "-O2",
        "-DGPGPU_NUM_CORES=8",
        "-o",
        str(tmp_path / "build/software/programs/example/example_x86"),
        str(tmp_path / "software/programs/example/example.c"),
    ]

    elf_command = tasks[f"{prefix}:elf"]["actions"][0][1][0]
    assert elf_command[0] == "/opt/riscv/bin/riscv64-unknown-elf-gcc"
    assert "-march=rv32im" in elf_command
    assert "-mabi=ilp32" in elf_command
    assert "-DGPGPU_NUM_CORES=8" in elf_command
    assert "-ffixed-x31" in elf_command
    assert "-mno-relax" in elf_command
    assert f"-Wl,-T,{tmp_path / 'software/programs/gpgpu.ld'}" in elf_command
    assert f"-Wl,-Map,{tmp_path / 'build/software/programs/example/example.map'}" in elf_command

    expected_targets = {
        tmp_path / "build/software/programs/example/example_x86",
        tmp_path / "build/software/programs/example/example.elf",
        tmp_path / "build/software/programs/example/example.map",
        tmp_path / "build/software/programs/example/example_dump_real.asm",
        tmp_path / "build/software/programs/example/example_program.asm",
        tmp_path / "build/software/programs/example/example_instructions.mem",
    }
    actual_targets = {
        Path(target)
        for task in tasks.values()
        for target in task.get("targets", [])
    }
    assert expected_targets <= actual_targets

    for task_name in (f"{prefix}:x86:build", f"{prefix}:elf"):
        fingerprint = tasks[task_name]["uptodate"][0]
        assert isinstance(fingerprint, config_changed)
        assert fingerprint.config == {"num_cores": 8}
        assert str(tmp_path / "software/programs/gpgpu_config.h") in tasks[task_name]["file_dep"]
        assert str(tmp_path / "software/programs/gpgpu_runtime.h") in tasks[task_name]["file_dep"]

    assert tasks[f"{prefix}:dump"]["task_dep"] == [f"{prefix}:elf"]
    assert tasks[f"{prefix}:assembly"]["task_dep"] == [f"{prefix}:dump"]
    assert tasks[f"{prefix}:mem"]["task_dep"] == [f"{prefix}:dump"]
    assert tasks[f"{prefix}:riscv:build"]["task_dep"] == [f"{prefix}:assembly"]
    assert tasks[f"{prefix}:all"]["task_dep"] == [
        f"{prefix}:riscv:build",
        f"{prefix}:x86:build",
    ]


def test_dump_transformations_match_makefile_filters(tmp_path: Path) -> None:
    dump = tmp_path / "example_dump_real.asm"
    assembly = tmp_path / "example_program.asm"
    memory = tmp_path / "example_instructions.mem"
    dump.write_text(
        """\
00000000 <_start>:
   0: 00000513 li a0,0
   4: 00b50533 add a0,a0,a1
   8: 8082 ret
not an instruction
""",
        encoding="utf-8",
    )

    programs.write_program_assembly(dump, assembly)
    programs.write_instruction_memory(dump, memory)

    assert assembly.read_text(encoding="utf-8") == (
        "li a0,0\n"
        "add a0,a0,a1\n"
        "ret\n"
    )
    assert memory.read_text(encoding="utf-8") == (
        "00000513\n"
        "00b50533\n"
    )


def test_non_program_directories_are_ignored(tmp_path: Path) -> None:
    config = make_repo(tmp_path)
    (tmp_path / "software/programs/not-a-program").mkdir()

    names = {task["name"] for task in programs.create_tasks(config)}  # type: ignore[arg-type]

    assert all("not-a-program" not in name for name in names)


def test_clean_task_refuses_symlink_escape_from_build_root(tmp_path: Path) -> None:
    config = make_repo(tmp_path)
    source_program = tmp_path / "software/programs/example"
    marker = source_program / "keep.c"
    marker.write_text("keep\n", encoding="utf-8")
    build_root = tmp_path / "build"
    build_root.mkdir()
    (build_root / "software").symlink_to(tmp_path / "software", target_is_directory=True)

    clean_task = tasks_by_name(config)["software:programs:example:clean"]
    action, arguments = clean_task["actions"][0]

    with pytest.raises(RuntimeError, match="symbolic link"):
        action(*arguments)
    assert marker.read_text(encoding="utf-8") == "keep\n"


@pytest.mark.skipif(shutil.which("gcc") is None, reason="gcc is not installed")
def test_x86_task_builds_and_runs_the_native_executable(tmp_path: Path) -> None:
    external_build = tmp_path / "external-output"
    config = make_repo(tmp_path, external_build)
    marker = tmp_path / "executed.txt"
    source = tmp_path / "software/programs/example/example.c"
    source.write_text(
        '#include <stdio.h>\n'
        'int main(void) {\n'
        f'    FILE *file = fopen("{marker}", "w");\n'
        '    if (file == NULL) return 1;\n'
        '    fputs("executed", file);\n'
        '    return fclose(file);\n'
        '}\n',
        encoding="utf-8",
    )
    tasks = tasks_by_name(config)
    build_task = tasks["software:programs:example:x86:build"]
    run_task = tasks["software:programs:example:x86"]

    build_action, build_arguments = build_task["actions"][0]
    build_action(*build_arguments)
    run_action, run_arguments = run_task["actions"][0]
    run_action(*run_arguments)

    executable = external_build / "software/programs/example/example_x86"
    assert executable.is_file()
    assert not (tmp_path / "software/programs/example/example_x86").exists()
    assert executable.stat().st_mode & 0o111
    assert run_task["task_dep"] == ["software:programs:example:x86:build"]
    assert run_task["uptodate"] == [False]
    assert marker.read_text(encoding="utf-8") == "executed"


REPO_ROOT = Path(__file__).resolve().parents[3]
SETTINGS = {"interface_version": 7, "use_irq": False, "irq_id": 61}
CONTROL_TEXT = (
    "localparam gpu_pkg::word_t REG_INFO = 'h0000;\n"
    "localparam gpu_pkg::word_t REG_STATUS = 'h0_024;\n"
    "localparam int unsigned STATUS_STOPPED_BIT = 2;\n"
    "localparam gpu_pkg::word_t STATUS_STOPPED_MASK = gpu_pkg::word_t'(1) << STATUS_STOPPED_BIT;\n"
)
MEMORY_TEXT = (
    "typedef enum logic [2:0] {\n"
    "    ST_OK = 3'd0, // comment, with comma\n"
    "    ST_SLVERR = 3'd4\n"
    "} mem_status_t;\n"
)
GPU_TEXT = (
    "localparam int unsigned IMEM_ENTRIES = 1024;\n"
    "localparam int unsigned DMEM_ENTRIES = 4096;\n"
)


def header_values(header: str) -> dict[str, str]:
    return dict(
        line.split()[1:3] for line in header.splitlines()
        if line.startswith("#define GPGPU_") and len(line.split()) == 3
    )


def test_committed_platform_header_matches_rtl_and_configuration() -> None:
    from config import resolve_config

    config = resolve_config(REPO_ROOT)
    [task] = host_platform.create_tasks(config)
    control, memory, gpu, settings, output = task["actions"][0][1]
    assert output == host_platform.header_path(config)
    assert settings == host_platform.host_settings(config)
    expected = host_platform.render_header(
        *(path.read_text(encoding="utf-8") for path in (control, memory, gpu)), settings
    )
    assert output.read_text(encoding="utf-8") == expected, (
        "gpgpu_platform.h is stale: run software:host:platform"
    )
    assert task["name"] == "software:host:platform"
    assert task["targets"] == [str(output)]
    assert {str(control), str(memory), str(gpu)} <= set(task["file_dep"])
    assert task["uptodate"][0].config == settings


def test_platform_header_derives_every_value_from_its_inputs() -> None:
    values = header_values(host_platform.render_header(CONTROL_TEXT, MEMORY_TEXT, GPU_TEXT, SETTINGS))
    assert values == {
        "GPGPU_INTERFACE_VERSION": "7U",
        "GPGPU_IMEM_WORDS": "1024U",
        "GPGPU_DMEM_WORDS": "4096U",
        "GPGPU_MAX_WORDS": "4096U",
        "GPGPU_REG_INFO": "0x0000U",
        "GPGPU_REG_STATUS": "0x0024U",
        "GPGPU_STATUS_STOPPED_BIT": "2U",
        "GPGPU_STATUS_STOPPED": "0x00000004U",
        "GPGPU_ST_OK": "0U",
        "GPGPU_ST_SLVERR": "4U",
        "GPGPU_USE_IRQ": "0",
        "GPGPU_IRQ_ID": "61U",
    }


@pytest.mark.parametrize(
    ("control", "memory", "gpu", "message"),
    [
        ("localparam gpu_pkg::word_t REG_X = 'h10 + 4;\n", MEMORY_TEXT, GPU_TEXT, "plain 'h literal"),
        ("", MEMORY_TEXT, GPU_TEXT, "no register offsets"),
        (CONTROL_TEXT, "typedef enum logic [2:0] {\n ST_OK = 0\n} mem_status_t;\n", GPU_TEXT, "explicit"),
        (CONTROL_TEXT, "", GPU_TEXT, "does not declare enum"),
        (CONTROL_TEXT, MEMORY_TEXT, "localparam int unsigned IMEM_ENTRIES = 2 * 1024;\n", "IMEM_ENTRIES"),
    ],
)
def test_platform_header_rejects_unparseable_rtl(control: str, memory: str, gpu: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        host_platform.render_header(control, memory, gpu, SETTINGS)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("software.host.use_irq", 1),
        ("software.host.irq_id", 0),
        ("architecture.interface_version", -1),
    ],
)
def test_platform_settings_have_no_fallback(key: str, value: object) -> None:
    values = {
        "architecture.interface_version": 2,
        "software.host.use_irq": True,
        "software.host.irq_id": 61,
        key: value,
    }

    class Config:
        def get(self, name: str):
            return values[name]

    with pytest.raises(ValueError, match=key):
        host_platform.host_settings(Config())  # type: ignore[arg-type]
