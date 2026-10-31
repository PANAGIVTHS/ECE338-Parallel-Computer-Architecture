from pathlib import Path
from io import StringIO
import sys

import pytest
from doit.tools import config_changed
from tools.tests import rtl


class StubResolvedConfig:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.random_seed = 12345

    def get(self, key):
        return {
            "architecture.num_cores": 8,
            "architecture.interface_version": 2,
            "architecture.ddr_enable": False,
            "hardware.vivado.fabric_clock_mhz": 35,
            "tools.python.command": sys.executable,
            "tools.verilator.command": "verilator-configured",
            "tools.make.command": "make-configured",
            "tools.native_cxx.command": "cxx-configured",
            "tests.rtl.trace.enabled": False,
            "tests.rtl.trace.verilator_flags": ["--trace-fst", "--trace-structs"],
            "tests.rtl.trace.dump_file": "dumpfile.fst",
            "tests.rtl.smx.testbench": "tests/hardware/rtl/tb_GPGPU.sv",
            "tests.rtl.smx.top": "tb_GPGPU_smx_only",
            "tests.rtl.smx.plusargs": {},
            "tests.rtl.e2e.testbench": "tests/hardware/rtl/tb_GPGPU_e2e.sv",
            "tests.rtl.e2e.top": "tb_GPGPU_e2e",
            "tests.rtl.e2e.plusargs": {"TEST_ROOT": "cases", "TEST_IDX": 1},
            "tests.rtl.smx.exclude_sources": ["interfaces"],
            "tests.rtl.e2e.exclude_sources": [],
            "paths.rtl.sources.gpgpu": "hardware/rtl/gpgpu",
            "hardware.sources.extensions": [".sv", ".v"],
            "hardware.sources.header_extensions": [".svh"],
            "hardware.sources.ordered": ["memory/MemoryInterface.sv"],
            "tests.rtl.range": "all",
            "tests.rtl.random.iterations": 100,
            "tests.rtl.random.seed": self.random_seed,
        }[key]

    @property
    def build_root(self):
        return self.repo_root / "build"


def make_repo(tmp_path):
    root = tmp_path / "hardware/rtl/gpgpu"
    for relative in ("constants.svh", "GPGPU.sv", "memory/MemoryInterface.sv",
                     "memory/Memory.sv", "control/Controller.sv", "sp/Processor.sv",
                     "interfaces/AXI4LiteTop.v"):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("// rtl\n")
    test_root = tmp_path / "tests/hardware/rtl"
    case = test_root / "cases/test1"
    case.mkdir(parents=True)
    (case / "program.asm").write_text("addi x1, x0, 1\n")
    (test_root / "tb_GPGPU.sv").write_text("// smx bench\n")
    (test_root / "tb_GPGPU_e2e.sv").write_text("// e2e bench\n")
    return StubResolvedConfig(tmp_path)


def tasks_by_name(config):
    return {task["name"]: task for task in rtl.create_tasks(config)}


def test_current_layout_generation_and_build_dependencies(tmp_path):
    tasks = tasks_by_name(make_repo(tmp_path))
    assert set(tasks) == {
        "hardware:identity", "tests:rtl:generate", "tests:rtl:random",
        *(f"tests:rtl:{suite}:{stage}" for suite in ("smx", "e2e") for stage in ("build", "run", "all")),
        *(f"tests:rtl:{stage}" for stage in ("build", "run", "all")),
    }
    generate = tasks["tests:rtl:generate"]
    case = tmp_path / "tests/hardware/rtl/cases/test1"
    assert str(case / "regfile_c7.mem") in generate["targets"]
    assert str(case / "regfile_c8.mem") not in generate["targets"]
    assert generate["actions"][1][1][0][-2:] == ["--num-cores", "8"]
    assert isinstance(generate["uptodate"][0], config_changed)
    assert generate["uptodate"][0].config == {"num_cores": 8}
    build = tasks["tests:rtl:smx:build"]
    command = build["actions"][0][1][0]
    assert command[0] == "verilator-configured"
    assert command[command.index("-MAKEFLAGS") + 1] == "CXX=cxx-configured LINK=cxx-configured"
    assert build["uptodate"][0].config == {"command": command, "make": "make-configured"}
    # The build identity comes from git through its own task, never at discovery.
    identity = tmp_path / "build/hardware/build_identity.txt"
    assert build["task_dep"] == ["hardware:identity"]
    assert str(identity) in build["file_dep"]
    assert build["actions"][0][1][-1] == identity
    assert tasks["hardware:identity"]["targets"] == [str(identity)]
    assert not any(arg.startswith("-GBUILD_") for arg in command)
    run = tasks["tests:rtl:smx:run"]
    assert run["task_dep"] == ["tests:rtl:generate", "tests:rtl:smx:build"]
    assert run["actions"][0][1][0] == build["targets"]
    assert run["uptodate"] == [False]
    rtl_root = tmp_path / "hardware/rtl/gpgpu"
    assert str(rtl_root / "interfaces/AXI4LiteTop.v") not in command
    e2e = tasks["tests:rtl:e2e:build"]["actions"][0][1][0]
    assert str(rtl_root / "interfaces/AXI4LiteTop.v") in e2e
    assert e2e[e2e.index("--top-module") + 1] == "tb_GPGPU_e2e"


def test_random_task_omits_seed_argument_when_configured_for_auto_seed(tmp_path):
    config = make_repo(tmp_path)
    config.random_seed = 0
    assert "--seed" not in tasks_by_name(config)["tests:rtl:random"]["actions"][0][1][0]


def test_run_simulation_writes_log_for_success(tmp_path):
    log = tmp_path / "simulation.log"
    rtl.run_simulation([sys.executable, "-c", "print('[SUCCESS] simulation passed')"], tmp_path, log)
    assert log.read_text() == "[SUCCESS] simulation passed\n"


@pytest.mark.parametrize("marker", ["[FAIL]", "[Error]", "[ERROR]"])
def test_run_simulation_fails_when_testbench_reports_failure(tmp_path, marker):
    with pytest.raises(RuntimeError, match="reported a failure"):
        rtl.run_simulation([sys.executable, "-c", f"print('{marker} mismatch')"], tmp_path, tmp_path / "simulation.log")


def test_run_simulation_propagates_nonzero_exit(tmp_path):
    with pytest.raises(RuntimeError, match="status 7"):
        rtl.run_simulation([sys.executable, "-c", "raise SystemExit(7)"], tmp_path, tmp_path / "simulation.log")


class FlushingTerminal(StringIO):
    def __init__(self):
        super().__init__()
        self.flush_count = 0

    def flush(self):
        self.flush_count += 1
        super().flush()


def test_run_simulation_streams_each_line_and_keeps_the_log(tmp_path):
    log = tmp_path / "simulation.log"
    terminal = FlushingTerminal()
    rtl.run_simulation([sys.executable, "-c", "import sys; print('first', flush=True); print('second', file=sys.stderr, flush=True)"], tmp_path, log, terminal=terminal)
    assert terminal.getvalue() == "first\nsecond\n"
    assert terminal.flush_count >= 2
    assert log.read_text() == "first\nsecond\n"


def test_compilation_does_not_reuse_objects_from_previous_toolchain(tmp_path):
    build = tmp_path / "smx"
    build.mkdir()
    (build / "old.o").write_text("previous compiler object")
    (build / "Vtb_GPGPU_smx_only__pch.h.fast.gch").write_text("old precompiled header")
    command = [sys.executable, "-c", "import sys; print('new build', *sys.argv[1:])"]
    identity = tmp_path / "build_identity.txt"
    identity.write_text("BUILD_HASH=12,BUILD_DIRTY=1\n")
    rtl.run_compilation(command, tmp_path, build, "configured-make", identity)
    assert not (build / "old.o").exists()
    assert not (build / "Vtb_GPGPU_smx_only__pch.h.fast.gch").exists()
    assert (build / "build.log").read_text() == "new build -GBUILD_HASH=12 -GBUILD_DIRTY=1\n"


def test_smx_runtime_resolves_cases_and_contains_dump(tmp_path):
    test_root = tmp_path / "tests"
    (test_root / "cases/test1").mkdir(parents=True)
    (test_root / "cases/test1/program.mem").write_text("00000000\n")
    log = tmp_path / "build/smx/simulation.log"
    rtl.run_smx([sys.executable, "-c", "from pathlib import Path; assert Path('cases/test1/program.mem').is_file(); Path('dumpfile.vcd').write_text('trace'); print('[SUCCESS]')"], test_root, log)
    assert (log.parent / "dumpfile.vcd").read_text() == "trace"
    assert (log.parent / "cases").resolve() == test_root / "cases"


def test_excluded_ordered_sources_are_dropped_per_suite(tmp_path):
    config = make_repo(tmp_path)
    lookup = config.get
    config.get = lambda key: ["memory"] if key == "tests.rtl.smx.exclude_sources" else lookup(key)
    tasks = tasks_by_name(config)
    rtl_root = tmp_path / "hardware/rtl/gpgpu"
    smx = tasks["tests:rtl:smx:build"]["actions"][0][1][0]
    e2e = tasks["tests:rtl:e2e:build"]["actions"][0][1][0]
    assert str(rtl_root / "memory/MemoryInterface.sv") not in smx
    assert e2e.index(str(rtl_root / "memory/MemoryInterface.sv")) < e2e.index(str(rtl_root / "GPGPU.sv"))


@pytest.mark.parametrize("exclude,dropped,kept", [
    (["memory"], ["memory/MemoryInterface.sv", "memory/Memory.sv"], ["control/Controller.sv"]),
    (["memory/Memory.sv"], ["memory/Memory.sv"], ["memory/MemoryInterface.sv"]),
    (["control/"], ["control/Controller.sv"], ["memory/Memory.sv"]),
    (["Memory.sv"], ["memory/Memory.sv"], ["memory/MemoryInterface.sv"]),
])
def test_exclude_sources_accepts_names_and_relative_paths(tmp_path, exclude, dropped, kept):
    config = make_repo(tmp_path)
    lookup = config.get
    config.get = lambda key: exclude if key == "tests.rtl.smx.exclude_sources" else lookup(key)
    command = tasks_by_name(config)["tests:rtl:smx:build"]["actions"][0][1][0]
    rtl_root = tmp_path / "hardware/rtl/gpgpu"
    assert not any(str(rtl_root / path) in command for path in dropped)
    assert all(str(rtl_root / path) in command for path in kept)


def git_checkout(tmp_path):
    """A repository whose RTL has one commit, for the build identity."""
    import subprocess

    rtl = tmp_path / "hardware/rtl/gpgpu"
    rtl.mkdir(parents=True)
    (rtl / "GPGPU.sv").write_text("module GPGPU; endmodule\n")
    (tmp_path / "README.md").write_text("outside the RTL\n")
    git = ["git", "-C", str(tmp_path), "-c", "user.name=fixture", "-c", "user.email=fixture@example.com"]
    subprocess.run([*git, "init", "--quiet"], check=True)
    subprocess.run([*git, "add", "--all"], check=True)
    subprocess.run([*git, "commit", "--quiet", "--no-gpg-sign", "-m", "rtl"], check=True)
    commit = subprocess.run([*git, "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout
    return rtl, int(commit[:7], 16)


class IdentityConfig:
    def __init__(self, root):
        self.repo_root = root
        self.build_root = root / "build"

    def get(self, key):
        return {"tools.git.command": "git", "paths.rtl.sources.gpgpu": "hardware/rtl/gpgpu"}[key]


def test_build_identity_is_the_rtl_commit_and_dirty_only_for_rtl_changes(tmp_path):
    from src.hardware_contract import build_identity, build_identity_path, write_build_identity

    rtl, commit = git_checkout(tmp_path)
    config = IdentityConfig(tmp_path)
    assert build_identity(config) == {"BUILD_HASH": commit, "BUILD_DIRTY": 0}
    (tmp_path / "README.md").write_text("edited outside the RTL\n")
    assert build_identity(config)["BUILD_DIRTY"] == 0
    (rtl / "GPGPU.sv").write_text("module GPGPU; wire edited; endmodule\n")
    assert build_identity(config) == {"BUILD_HASH": commit, "BUILD_DIRTY": 1}

    # Rewritten only on change, so dependents compare the file as unchanged.
    output = build_identity_path(config)
    write_build_identity(config, output)
    assert output.read_text() == f"BUILD_HASH={commit},BUILD_DIRTY=1\n"
    stamp = output.stat().st_mtime_ns
    write_build_identity(config, output)
    assert output.stat().st_mtime_ns == stamp


def test_build_identity_requires_an_rtl_commit(tmp_path):
    import subprocess
    from src.hardware_contract import build_identity

    (tmp_path / "hardware/rtl/gpgpu").mkdir(parents=True)
    subprocess.run(["git", "-C", str(tmp_path), "init", "--quiet"], check=True)
    with pytest.raises((ValueError, subprocess.CalledProcessError)):
        build_identity(IdentityConfig(tmp_path))


def test_hdl_parameters_round_trip_and_reject_malformed_text():
    from src.hardware_contract import format_parameters, parse_parameters

    parameters = {"INTERFACE_VERSION": 2, "CLOCK_KHZ": 35000, "DDR_ENABLE": 0}
    assert format_parameters(parameters) == "INTERFACE_VERSION=2,CLOCK_KHZ=35000,DDR_ENABLE=0"
    assert parse_parameters(format_parameters(parameters) + "\n") == parameters
    for text in ("A=1,A=2", "lower=1", "A=-1", "A=1 B=2", ""):
        with pytest.raises(ValueError):
            parse_parameters(text)


VALID_STATIC = {
    "architecture.interface_version": 2,
    "architecture.ddr_enable": False,
    "hardware.vivado.fabric_clock_mhz": 35.714,
}


def static_config(values):
    class Config:
        def get(self, name):
            return values[name]
    return Config()


def test_static_hdl_parameters_come_from_configuration():
    from src.hardware_contract import static_hdl_parameters

    assert static_hdl_parameters(static_config(VALID_STATIC)) == {
        "INTERFACE_VERSION": 2, "CLOCK_KHZ": 35714, "DDR_ENABLE": 0,
    }


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("architecture.interface_version", 0),
        ("architecture.ddr_enable", 1),
        ("hardware.vivado.fabric_clock_mhz", 0),
    ],
)
def test_static_hdl_parameters_have_no_fallback(key, value):
    from src.hardware_contract import static_hdl_parameters

    with pytest.raises(ValueError, match=key):
        static_hdl_parameters(static_config({**VALID_STATIC, key: value}))
