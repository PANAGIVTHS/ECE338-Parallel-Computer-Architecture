"""pydoit tasks for the directed RTL simulation pipeline."""

from __future__ import annotations

from pathlib import Path
import re
import subprocess
import sys
from typing import TYPE_CHECKING, Any, TextIO

if TYPE_CHECKING:
    from config import ResolvedConfig


_TEST_CASE = re.compile(r"test\d+")
_FAILURE_MARKERS = ("[FAIL]", "[Error]", "[ERROR]")


def run_command(command: list[str], cwd: Path, create_directory: Path | None = None) -> None:
    """Run one command in *cwd*, optionally creating an output directory first."""

    if create_directory is not None:
        create_directory.mkdir(parents=True, exist_ok=True)
    subprocess.run(command, cwd=cwd, check=True)


def run_simulation(
    command: list[str],
    cwd: Path,
    log: Path,
    terminal: TextIO | None = None,
) -> None:
    """Stream an RTL simulation to the terminal and log, rejecting failures."""

    log.parent.mkdir(parents=True, exist_ok=True)
    terminal = terminal or sys.__stdout__
    failure_reported = False

    with log.open("w", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        if process.stdout is None:  # pragma: no cover - guaranteed by PIPE
            raise RuntimeError("RTL simulator output pipe was not created")

        for line in process.stdout:
            terminal.write(line)
            terminal.flush()
            log_file.write(line)
            log_file.flush()
            failure_reported = failure_reported or any(
                marker in line for marker in _FAILURE_MARKERS
            )

        returncode = process.wait()

    if returncode != 0:
        raise RuntimeError(f"RTL simulator exited with status {returncode}")
    if failure_reported:
        raise RuntimeError("RTL simulation reported a failure")


def _configured_command(config: ResolvedConfig, key: str) -> str:
    value = config.get(key)
    if not isinstance(value, str):
        raise TypeError(f"{key} must be a string")
    return value


def _test_cases(cases_root: Path) -> list[Path]:
    return sorted(
        (
            path
            for path in cases_root.iterdir()
            if path.is_dir()
            and _TEST_CASE.fullmatch(path.name)
            and (path / "program.asm").is_file()
        ),
        key=lambda path: int(path.name.removeprefix("test")),
    )


def create_tasks(config: ResolvedConfig) -> list[dict[str, Any]]:
    """Create generation, build, run, and aggregate tasks for RTL tests."""

    repo_root = config.repo_root
    rtl_root = config.repo_path("paths.hardware.rtl")
    tests_root = config.repo_path("paths.tests.root")
    test_root = tests_root / "hardware/rtl"
    cases_root = test_root / "cases"
    build_root = config.repo_path("paths.build.root") / "tests/rtl"

    python = _configured_command(config, "tools.python.command")
    iverilog = _configured_command(config, "tools.iverilog.command")
    vvp = _configured_command(config, "tools.vvp.command")

    assembler = repo_root / "tools/tests/assembler.py"
    expected_generator = repo_root / "tools/tests/expected_generator.py"
    testbenches = {
        "e2e": test_root / "tb_GPGPU_e2e.v",
        "smx": test_root / "tb_GPGPU.v",
    }

    cases = _test_cases(cases_root)
    assembly_sources = [case / "program.asm" for case in cases]
    optional_seeds = [
        case / "dmem_seed.mem"
        for case in cases
        if (case / "dmem_seed.mem").is_file()
    ]
    generated_targets = [
        output
        for case in cases
        for output in (
            case / "program.mem",
            case / "data.mem",
            *(case / f"regfile_c{core}.mem" for core in range(32)),
        )
    ]

    rtl_sources = sorted(
        (
            *rtl_root.glob("*.vh"),
            *rtl_root.glob("*.v"),
            *rtl_root.glob("memory/*.v"),
            *rtl_root.glob("sp/*.v"),
        )
    )

    tasks: list[dict[str, Any]] = [
        {
            "name": "tests:rtl:generate",
            "actions": [
                (run_command, [[python, str(assembler)], test_root]),
                (run_command, [[python, str(expected_generator)], test_root]),
            ],
            "file_dep": [
                str(assembler),
                str(expected_generator),
                *(str(source) for source in assembly_sources),
                *(str(seed) for seed in optional_seeds),
            ],
            "targets": [str(target) for target in generated_targets],
            "clean": True,
        }
    ]

    for suite, testbench in testbenches.items():
        suite_build_root = build_root / suite
        executable = suite_build_root / "main"
        simulation_log = suite_build_root / "simulation.log"
        build_task = f"tests:rtl:{suite}:build"
        run_task = f"tests:rtl:{suite}:run"

        compile_command = [
            iverilog,
            "-Wall",
            "-Wno-timescale",
            "-Winfloop",
            "-I",
            str(rtl_root),
            "-DSIM",
            "-o",
            str(executable),
            str(testbench),
            *(str(source) for source in rtl_sources),
        ]

        tasks.extend(
            [
                {
                    "name": build_task,
                    "actions": [
                        (run_command, [compile_command, repo_root, suite_build_root])
                    ],
                    "file_dep": [str(testbench), *(str(source) for source in rtl_sources)],
                    "targets": [str(executable)],
                    "clean": True,
                },
                {
                    "name": run_task,
                    "actions": [
                        (
                            run_simulation,
                            [[vvp, "-i", str(executable)], test_root, simulation_log],
                        )
                    ],
                    "task_dep": ["tests:rtl:generate", build_task],
                    "targets": [str(simulation_log)],
                    "uptodate": [False],
                    "clean": True,
                },
                {
                    "name": f"tests:rtl:{suite}:all",
                    "actions": None,
                    "task_dep": [run_task],
                },
            ]
        )

    tasks.extend(
        [
            {
                "name": "tests:rtl:build",
                "actions": None,
                "task_dep": ["tests:rtl:e2e:build", "tests:rtl:smx:build"],
            },
            {
                "name": "tests:rtl:run",
                "actions": None,
                "task_dep": ["tests:rtl:e2e:run", "tests:rtl:smx:run"],
            },
            {
                "name": "tests:rtl:all",
                "actions": None,
                "task_dep": ["tests:rtl:run"],
            },
        ]
    )
    return tasks
