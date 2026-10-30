"""pydoit tasks for the directed RTL simulation pipeline."""

from __future__ import annotations

from pathlib import Path
import os
import re
import shlex
import subprocess
import sys
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TextIO

from doit.tools import config_changed
from src.project_paths import ProjectPaths
from src.hardware_contract import rtl_root, rtl_sources, string_list

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
    env: dict[str, str] | None = None,
) -> None:
    """Stream an RTL simulation to the terminal and log, rejecting failures."""

    log.parent.mkdir(parents=True, exist_ok=True)
    terminal = terminal or sys.__stdout__
    failure_reported = False
    with log.open("w", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
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

def _configured_positive_int(config: ResolvedConfig, key: str) -> int:
    value = config.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise TypeError(f"{key} must be a positive integer")
    return value

def _configured_bool(config: ResolvedConfig, key: str) -> bool:
    value = config.get(key)
    if not isinstance(value, bool):
        raise TypeError(f"{key} must be a boolean")
    return value

def _configured_plusargs(config: ResolvedConfig, key: str) -> list[str]:
    """Render a {NAME: value} mapping as simulator +NAME=value arguments."""
    value = config.get(key)
    if not isinstance(value, Mapping) or not all(
        isinstance(name, str) and isinstance(arg, (str, int, float)) and not isinstance(arg, bool)
        for name, arg in value.items()
    ):
        raise TypeError(f"{key} must be a mapping of names to strings or numbers")
    return [f"+{name}={arg}" for name, arg in value.items()]

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


def rtl_range_plusargs(value: str) -> list[str]:
    """Translate an inclusive directed-test range to the shared bench protocol."""
    if value == "all":
        return []
    match = re.fullmatch(r"([1-9][0-9]*)-([1-9][0-9]*)", value)
    if match is None:
        raise ValueError('tests.rtl.range must be "all" or an inclusive range such as "1-10"')
    first, last = map(int, match.groups())
    if first > last or last > 2**31 - 1:
        raise ValueError("tests.rtl.range requires 1 <= start <= end <= 2147483647")
    return [f"+TEST_IDX={first}", f"+TEST_END={last}"]


def run_compilation(command: list[str], cwd: Path, build: Path, make: str) -> None:
    """Build with configured native prerequisites and preserve live build output."""
    build.mkdir(parents=True, exist_ok=True)
    # doit decides whether to rebuild. Once invalidated, make must not reuse
    # objects/PCH from a different compiler or set of compile options.
    for pattern in ("*.o", "*.a", "*.gch", "*.gch.d", "main"):
        for artifact in build.glob(pattern):
            artifact.unlink()
    run_simulation(command, cwd, build / "build.log", env={**os.environ, "MAKE": make})

def run_smx(command: list[str], test_root: Path, log: Path) -> None:
    """Keep simulator artifacts under the build root; resolve cases/ via a link."""
    first = next((int(arg.split("=", 1)[1]) for arg in command if arg.startswith("+TEST_IDX=")), None)
    last = next((int(arg.split("=", 1)[1]) for arg in command if arg.startswith("+TEST_END=")), None)
    if first is not None and last is not None:
        available = {int(case.name.removeprefix("test")) for case in _test_cases(test_root / "cases")}
        # Check completeness without iterating a potentially huge configured span.
        selected = sorted(index for index in available if first <= index <= last)
        expected = first
        for index in selected:
            if index != expected:
                break
            expected += 1
        if expected <= last:
            raise ValueError(f"tests.rtl.range selects missing test{expected}/program.asm")
    runtime = log.parent
    runtime.mkdir(parents=True, exist_ok=True)
    cases = runtime / "cases"
    if not cases.is_symlink():
        cases.symlink_to(test_root / "cases", target_is_directory=True)
    elif cases.resolve() != (test_root / "cases").resolve():
        cases.unlink()
        cases.symlink_to(test_root / "cases", target_is_directory=True)
    run_simulation(command, runtime, log)

def create_tasks(config: ResolvedConfig) -> list[dict[str, Any]]:
    """Create generation, build, run, and aggregate tasks for RTL tests."""
    repo_root = config.repo_root
    paths = ProjectPaths.from_config(config)
    test_root = paths.rtl_tests
    cases_root = test_root / "cases"
    build_root = paths.rtl_test_build
    python = _configured_command(config, "tools.python.command")
    verilator = _configured_command(config, "tools.verilator.command")
    make = _configured_command(config, "tools.make.command")
    cxx = _configured_command(config, "tools.native_cxx.command")
    trace = _configured_bool(config, "tests.rtl.trace.enabled")
    trace_flags = string_list(config, "tests.rtl.trace.verilator_flags")
    dump_file = _configured_command(config, "tests.rtl.trace.dump_file")
    num_cores = _configured_positive_int(config, "architecture.num_cores")
    range_args = rtl_range_plusargs(_configured_command(config, "tests.rtl.range"))
    assembler = repo_root / "tools/tests/assembler.py"
    expected_generator = repo_root / "tools/tests/expected_generator.py"
    random_tester = repo_root / "tools/tests/random_tester.py"
    # Suite names are the task namespace; everything else about a suite
    # (bench file, top module, tracing, runtime plusargs) comes from config.
    suites = ("smx", "e2e")
    testbenches = {
        suite: repo_root / _configured_command(config, f"tests.rtl.{suite}.testbench")
        for suite in suites
    }
    testbench_tops = {
        suite: _configured_command(config, f"tests.rtl.{suite}.top") for suite in suites
    }
    run_plusargs = {
        suite: _configured_plusargs(config, f"tests.rtl.{suite}.plusargs") for suite in suites
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
            *(case / f"regfile_c{core}.mem" for core in range(num_cores)),
        )
    ]

    # RTL sources: hardware.sources under paths.rtl.sources.gpgpu, minus each
    # suite's exclude_sources list (e.g. the SMX build drops the AXI wrapper
    # the E2E build needs). Headers are only tracked as build dependencies.
    rtl_src_root = rtl_root(config)
    suite_sources, suite_headers = {}, {}
    for suite in suites:
        suite_sources[suite], suite_headers[suite] = rtl_sources(
            config, string_list(config, f"tests.rtl.{suite}.exclude_sources")
        )

    tasks: list[dict[str, Any]] = [
        {
            "name": "tests:rtl:generate",
            "actions": [
                (run_command, [[python, str(assembler)], test_root]),
                (
                    run_command,
                    [
                        [
                            python,
                            str(expected_generator),
                            "--num-cores",
                            str(num_cores),
                        ],
                        test_root,
                    ],
                ),
            ],
            "file_dep": [
                str(assembler),
                str(expected_generator),
                *(str(source) for source in assembly_sources),
                *(str(seed) for seed in optional_seeds),
            ],
            "targets": [str(target) for target in generated_targets],
            "uptodate": [config_changed({"num_cores": num_cores})],
            "clean": True,
        }
    ]
    for suite, testbench in testbenches.items():
        sources = suite_sources[suite]
        suite_build_root = build_root / suite
        executable = suite_build_root / "main"
        simulation_log = suite_build_root / "simulation.log"
        build_task = f"tests:rtl:{suite}:build"
        run_task = f"tests:rtl:{suite}:run"
        compile_command = [
            verilator, "--binary", "--timing", "--assert", "--autoflush", "-Wno-fatal",
            "--timescale", "1ns/1ps", f"-I{rtl_src_root}", "-DSIM",
            "--top-module", testbench_tops[suite], f"-GNUM_CORES={num_cores}",
            "--Mdir", str(suite_build_root), "-o", executable.name,
            "-MAKEFLAGS", shlex.join([f"CXX={cxx}", f"LINK={cxx}"]),
            *(trace_flags if trace else []),
            *(str(source) for source in sources), str(testbench),
        ]
        tasks.extend(
            [
                {
                    "name": build_task,
                    "actions": [
                        (run_compilation, [compile_command, repo_root, suite_build_root, make])
                    ],
                    "file_dep": [str(testbench), *(str(source) for source in (*sources, *suite_headers[suite]))],
                    "targets": [str(executable)],
                    "uptodate": [config_changed({"command": compile_command, "make": make})],
                    "clean": True,
                },
                {
                    "name": run_task,
                    "actions": [
                        (
                            run_smx,
                            [
                                [
                                    str(executable),
                                    *run_plusargs[suite],
                                    *([f"+DUMP_FILE={dump_file}"] if trace else []),
                                    *range_args
                                ],
                                test_root,
                                simulation_log,
                            ],
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
    random_iterations = _configured_positive_int(
        config, "tests.rtl.random.iterations"
    )
    random_seed = config.get("tests.rtl.random.seed")
    if random_seed is not None and (
        not isinstance(random_seed, int) or isinstance(random_seed, bool)
    ):
        raise TypeError("tests.rtl.random.seed must be an integer or null")
    random_build_root = build_root / "random"
    random_log = random_build_root / "random.log"
    random_command = [
        python,
        str(random_tester),
        "--iterations",
        str(random_iterations),
        "--num-cores",
        str(num_cores),
    ]
    if random_seed != 0:
        random_command.extend(["--seed", str(random_seed)])
    random_command.extend(
        [
            "--python",
            python,
            "--simulator",
            str(build_root / "smx/main"),
            "--test-root",
            str(test_root),
            "--log",
            str(random_log),
        ]
    )
    tasks.append(
        {
            "name": "tests:rtl:random",
            "actions": [
                (run_command, [random_command, repo_root, random_build_root])
            ],
            "file_dep": [str(random_tester), str(assembler), str(expected_generator)],
            "task_dep": ["tests:rtl:smx:build"],
            "targets": [str(random_log)],
            "uptodate": [False],
            "clean": True,
        }
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