from pathlib import Path
import sys
import pytest
from tools.tests import rtl


class Config:
    def __init__(self, root):
        self.repo_root = root
        self.num_cores = 8
        self.trace = False
        self.verilator = "configured-verilator"

    @property
    def build_root(self):
        return self.repo_root / "custom-build"

    def get(self, key):
        return {
            "architecture.num_cores": self.num_cores,
            "tools.python.command": sys.executable,
            "tools.verilator.command": self.verilator,
            "tools.make.command": "configured-make",
            "tools.native_cxx.command": "configured-cxx",
            "tests.rtl.trace.enabled": self.trace,
            "tests.rtl.trace.verilator_flags": ["--trace-fst", "--trace-structs"],
            "tests.rtl.trace.dump_file": "dumpfile.fst",
            "tests.rtl.smx.testbench": "tests/hardware/rtl/tb_GPGPU.sv",
            "tests.rtl.smx.top": "tb_GPGPU_smx_only",
            "tests.rtl.smx.plusargs": {},
            "tests.rtl.e2e.testbench": "tests/hardware/rtl/tb_GPGPU_e2e.sv",
            "tests.rtl.e2e.top": "tb_GPGPU_e2e",
            "tests.rtl.e2e.plusargs": {"TEST_ROOT": "cases", "TEST_IDX": 1},
            "tests.rtl.smx.exclude_sources": ["experimental", "interfaces"],
            "tests.rtl.e2e.exclude_sources": ["experimental", "HostControllerProcessor.sv"],
            "paths.rtl.sources.gpgpu": "hardware/rtl/gpgpu",
            "hardware.sources.extensions": [".sv", ".v"],
            "hardware.sources.header_extensions": [".svh"],
            "hardware.sources.ordered": [
                "packages/gpu_pkg.sv",
                "control/ControlPkg.sv",
                "memory/MemoryInterface.sv",
                "memory/MemorySubsystemPkg.sv",
                "memory/MemorySubsystemInterface.sv",
            ],
            "tests.rtl.range": "all",
            "tests.rtl.random.iterations": 2,
            "tests.rtl.random.seed": 12345,
        }[key]


def tasks(config):
    return {t["name"]: t for t in rtl.create_tasks(config)}


def test_real_checkout_verilator_sources_and_core_count():
    repo = Path(__file__).resolve().parents[3]
    config = Config(repo)
    graph = tasks(config)
    build = graph["tests:rtl:smx:build"]
    command = build["actions"][0][1][0]
    root = repo / "hardware/rtl/gpgpu"
    assert command[0] == "configured-verilator"
    assert all(Path(p).is_file() for p in build["file_dep"])
    for flag in ("--binary", "--timing", "--assert", "--autoflush", "-GNUM_CORES=8"):
        assert flag in command
    assert command[command.index("--top-module") + 1] == "tb_GPGPU_smx_only"
    assert command.index(str(root / "memory/MemoryInterface.sv")) < command.index(str(root / "GPGPU.sv"))
    for source in ("control/ExecutionController.sv", "sp/StreamingProcessor.sv"):
        assert str(root / source) in command
    assert str(root / "constants.svh") in build["file_dep"]
    assert str(root / "constants.svh") not in command
    assert not any("experimental" in s or "AXI4Lite" in s for s in command)
    assert not any(s in command for s in ("-P", "-s", "-Winfloop", "-Wno-timescale"))
    assert command[command.index("--Mdir") + 1] == str(config.build_root / "tests/rtl/smx")
    assert graph["tests:rtl:generate"]["actions"][1][1][0][-2:] == ["--num-cores", "8"]
    assert graph["tests:rtl:smx:run"]["actions"][0][1][0] == build["targets"]
    config.num_cores = 4
    config.verilator = "another-verilator"
    changed = tasks(config)
    assert "-GNUM_CORES=4" in changed["tests:rtl:smx:build"]["actions"][0][1][0]
    assert changed["tests:rtl:smx:build"]["uptodate"][0].config != build["uptodate"][0].config
    assert changed["tests:rtl:generate"]["uptodate"][0].config == {"num_cores": 4}


def test_e2e_builds_axi_top_and_aggregate_requires_both_suites():
    repo = Path(__file__).resolve().parents[3]
    graph = tasks(Config(repo))
    root = repo / "hardware/rtl/gpgpu"
    command = graph["tests:rtl:e2e:build"]["actions"][0][1][0]
    assert command[command.index("--top-module") + 1] == "tb_GPGPU_e2e"
    assert command[-1] == str(repo / "tests/hardware/rtl/tb_GPGPU_e2e.sv")
    for source in ("interfaces/AXI4LiteSlave.sv", "interfaces/AXI4LiteTop.v"):
        assert str(root / source) in command
        assert str(root / source) in graph["tests:rtl:e2e:build"]["file_dep"]
    assert str(root / "interfaces/HostControllerProcessor.sv") not in command
    assert command[command.index("--Mdir") + 1] == str(repo / "custom-build/tests/rtl/e2e")
    assert graph["tests:rtl:e2e:run"]["task_dep"] == ["tests:rtl:generate", "tests:rtl:e2e:build"]
    assert graph["tests:rtl:e2e:all"]["task_dep"] == ["tests:rtl:e2e:run"]
    assert graph["tests:rtl:build"]["task_dep"] == ["tests:rtl:e2e:build", "tests:rtl:smx:build"]
    assert graph["tests:rtl:run"]["task_dep"] == ["tests:rtl:e2e:run", "tests:rtl:smx:run"]
    assert graph["tests:rtl:all"]["task_dep"] == ["tests:rtl:run"]


def test_trace_and_random_use_native_executable():
    config = Config(Path(__file__).resolve().parents[3])
    config.trace = True
    graph = tasks(config)
    for suite in ("smx", "e2e"):
        build = graph[f"tests:rtl:{suite}:build"]["actions"][0][1][0]
        assert "--trace-fst" in build and "--trace-structs" in build
        assert "+DUMP_FILE=dumpfile.fst" in graph[f"tests:rtl:{suite}:run"]["actions"][0][1][0]
    run = graph["tests:rtl:e2e:run"]["actions"][0][1][0]
    assert run[1:3] == ["+TEST_ROOT=cases", "+TEST_IDX=1"]
    command = graph["tests:rtl:random"]["actions"][0][1][0]
    assert "--vvp" not in command
    assert command[command.index("--simulator") + 1] == graph["tests:rtl:smx:build"]["targets"][0]


@pytest.mark.parametrize("key", [
    f"tests.rtl.{suite}.{option}"
    for suite in ("smx", "e2e")
    for option in ("testbench", "top", "exclude_sources", "plusargs")
] + ["paths.rtl.sources.gpgpu"]
  + [f"hardware.sources.{option}" for option in ("extensions", "header_extensions", "ordered")]
  + ["tests.rtl.trace.enabled", "tests.rtl.trace.verilator_flags", "tests.rtl.trace.dump_file"])
def test_suite_settings_have_no_fallback(key):
    config = Config(Path(__file__).resolve().parents[3])
    lookup = config.get
    config.get = lambda k: (_ for _ in ()).throw(KeyError(k)) if k == key else lookup(k)
    with pytest.raises(KeyError, match=key):
        tasks(config)
