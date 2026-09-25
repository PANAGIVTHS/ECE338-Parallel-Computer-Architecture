from __future__ import annotations

from pathlib import Path
import sys
from io import StringIO

import pytest
from doit.tools import config_changed

from tools.tests import rtl


class StubResolvedConfig:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self.random_seed = 12345

    def get(self, key: str):
        values = {
            "tools.python.command": sys.executable,
            "tools.iverilog.command": "iverilog-configured",
            "tools.vvp.command": "vvp-configured",
            "tests.rtl.random.iterations": 100,
            "tests.rtl.random.seed": self.random_seed,
        }
        return values[key]

    def repo_path(self, key: str) -> Path:
        values = {
            "paths.hardware.rtl": self.repo_root / "hardware/rtl",
            "paths.tests.root": self.repo_root / "tests",
            "paths.build.root": self.repo_root / "build",
        }
        return values[key]


def make_repo(tmp_path: Path) -> StubResolvedConfig:
    rtl_root = tmp_path / "hardware/rtl"
    for relative in ("constants.vh", "GPGPU.v", "memory/Memory.v", "sp/Processor.v"):
        path = rtl_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("// rtl\n", encoding="utf-8")

    test_root = tmp_path / "tests/hardware/rtl"
    case = test_root / "cases/test1"
    case.mkdir(parents=True)
    (case / "program.asm").write_text("addi x1, x0, 1\n", encoding="utf-8")
    (test_root / "tb_GPGPU_e2e.v").write_text("// e2e testbench\n", encoding="utf-8")
    (test_root / "tb_GPGPU.v").write_text("// smx testbench\n", encoding="utf-8")

    tools_root = tmp_path / "tools/tests"
    tools_root.mkdir(parents=True)
    (tools_root / "assembler.py").write_text("# assembler\n", encoding="utf-8")
    (tools_root / "expected_generator.py").write_text("# expected\n", encoding="utf-8")
    (tools_root / "random_tester.py").write_text("# random tester\n", encoding="utf-8")
    return StubResolvedConfig(tmp_path)


def tasks_by_name(config: StubResolvedConfig) -> dict[str, dict]:
    return {task["name"]: task for task in rtl.create_tasks(config)}  # type: ignore[arg-type]


def test_create_tasks_defines_distinct_e2e_and_smx_pipelines(tmp_path: Path) -> None:
    tasks = tasks_by_name(make_repo(tmp_path))

    assert set(tasks) == {
        "tests:rtl:generate",
        "tests:rtl:e2e:build",
        "tests:rtl:e2e:run",
        "tests:rtl:e2e:all",
        "tests:rtl:smx:build",
        "tests:rtl:smx:run",
        "tests:rtl:smx:all",
        "tests:rtl:random",
        "tests:rtl:build",
        "tests:rtl:run",
        "tests:rtl:all",
    }

    generate_targets = set(tasks["tests:rtl:generate"]["targets"])
    case = tmp_path / "tests/hardware/rtl/cases/test1"
    assert str(case / "program.mem") in generate_targets
    assert str(case / "data.mem") in generate_targets
    assert str(case / "regfile_c0.mem") in generate_targets
    assert str(case / "regfile_c31.mem") in generate_targets

    for suite, testbench in (("e2e", "tb_GPGPU_e2e.v"), ("smx", "tb_GPGPU.v")):
        executable = tmp_path / f"build/tests/rtl/{suite}/main"
        log = tmp_path / f"build/tests/rtl/{suite}/simulation.log"

        build_task = tasks[f"tests:rtl:{suite}:build"]
        assert build_task["targets"] == [str(executable)]
        build_command = build_task["actions"][0][1][0]
        assert build_command[0] == "iverilog-configured"
        assert "-DSIM" in build_command
        assert str(tmp_path / f"tests/hardware/rtl/{testbench}") in build_command
        assert len(build_task["uptodate"]) == 1
        tool_fingerprint = build_task["uptodate"][0]
        assert isinstance(tool_fingerprint, config_changed)
        assert tool_fingerprint.config == {"command": build_command}

        run_task = tasks[f"tests:rtl:{suite}:run"]
        assert run_task["task_dep"] == [
            "tests:rtl:generate",
            f"tests:rtl:{suite}:build",
        ]
        assert run_task["targets"] == [str(log)]
        assert run_task["uptodate"] == [False]
        assert run_task["actions"][0][1][0] == [
            "vvp-configured",
            "-i",
            str(executable),
        ]
        assert tasks[f"tests:rtl:{suite}:all"]["task_dep"] == [
            f"tests:rtl:{suite}:run"
        ]

    assert tasks["tests:rtl:build"]["task_dep"] == [
        "tests:rtl:e2e:build",
        "tests:rtl:smx:build",
    ]
    assert tasks["tests:rtl:run"]["task_dep"] == [
        "tests:rtl:e2e:run",
        "tests:rtl:smx:run",
    ]
    assert tasks["tests:rtl:all"]["task_dep"] == ["tests:rtl:run"]

    random_task = tasks["tests:rtl:random"]
    assert random_task["task_dep"] == ["tests:rtl:smx:build"]
    assert random_task["uptodate"] == [False]
    assert random_task["targets"] == [
        str(tmp_path / "build/tests/rtl/random/random.log")
    ]
    random_command = random_task["actions"][0][1][0]
    assert random_command == [
        sys.executable,
        str(tmp_path / "tools/tests/random_tester.py"),
        "--iterations",
        "100",
        "--seed",
        "12345",
        "--python",
        sys.executable,
        "--vvp",
        "vvp-configured",
        "--simulator",
        str(tmp_path / "build/tests/rtl/smx/main"),
        "--test-root",
        str(tmp_path / "tests/hardware/rtl"),
        "--log",
        str(tmp_path / "build/tests/rtl/random/random.log"),
    ]



def test_random_task_omits_seed_argument_when_configured_for_auto_seed(
    tmp_path: Path,
) -> None:
    config = make_repo(tmp_path)
    config.random_seed = 0

    command = tasks_by_name(config)["tests:rtl:random"]["actions"][0][1][0]

    assert "--seed" not in command

def test_run_simulation_writes_log_for_success(tmp_path: Path) -> None:
    log = tmp_path / "simulation.log"

    rtl.run_simulation(
        [sys.executable, "-c", "print('[SUCCESS] simulation passed')"],
        tmp_path,
        log,
    )

    assert log.read_text(encoding="utf-8") == "[SUCCESS] simulation passed\n"


def test_run_simulation_fails_when_testbench_reports_failure(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="reported a failure"):
        rtl.run_simulation(
            [sys.executable, "-c", "print('[FAIL] mismatch')"],
            tmp_path,
            tmp_path / "simulation.log",
        )


class FlushingTerminal(StringIO):
    def __init__(self) -> None:
        super().__init__()
        self.flush_count = 0

    def flush(self) -> None:
        self.flush_count += 1
        super().flush()


def test_run_simulation_streams_each_line_and_keeps_the_log(tmp_path: Path) -> None:
    log = tmp_path / "simulation.log"
    terminal = FlushingTerminal()

    rtl.run_simulation(
        [
            sys.executable,
            "-c",
            "import sys; print('first', flush=True); print('second', file=sys.stderr, flush=True)",
        ],
        tmp_path,
        log,
        terminal=terminal,
    )

    assert terminal.getvalue() == "first\nsecond\n"
    assert terminal.flush_count >= 2
    assert log.read_text(encoding="utf-8") == "first\nsecond\n"
