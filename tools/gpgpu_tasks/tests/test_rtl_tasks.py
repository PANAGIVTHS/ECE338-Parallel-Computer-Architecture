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
            "tests.rtl.ddr.testbench": "tests/hardware/rtl/tb_GPGPU_ddr.sv",
            "tests.rtl.ddr.top": "tb_GPGPU_ddr",
            "tests.rtl.ddr.plusargs": {},
            "tests.rtl.smx.exclude_sources": ["interfaces"],
            "tests.rtl.e2e.exclude_sources": [],
            "tests.rtl.ddr.exclude_sources": [],
            "tests.rtl.smx.parameters": {},
            "tests.rtl.e2e.parameters": {},
            "tests.rtl.ddr.parameters": {"DDR_ENABLE": 1, "AXI_SLAVE_SEED": 7},
            "tests.rtl.axi_slave.source": "tests/hardware/rtl/AXI4SlaveMemory.sv",
            "tests.rtl.axi_slave.parameters": {"AXI_SLAVE_LATENCY_MAX": 9, "AXI_SLAVE_SEED": 3},
            "paths.rtl.sources.gpgpu": "hardware/rtl/gpgpu",
            "hardware.vivado.exclude_sources": [],
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
                     "interfaces/AXI4Top.v"):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("// rtl\n")
    test_root = tmp_path / "tests/hardware/rtl"
    case = test_root / "cases/test1"
    case.mkdir(parents=True)
    (case / "program.asm").write_text("addi x1, x0, 1\n")
    (test_root / "tb_GPGPU.sv").write_text("// smx bench\n")
    (test_root / "tb_GPGPU_e2e.sv").write_text("// e2e bench\n")
    (test_root / "tb_GPGPU_ddr.sv").write_text("// ddr bench\n")
    (test_root / "tb_e2e_host.svh").write_text("// shared bench harness\n")
    (test_root / "AXI4SlaveMemory.sv").write_text("// slave model\n")
    return StubResolvedConfig(tmp_path)


def tasks_by_name(config):
    return {task["name"]: task for task in rtl.create_tasks(config)}


def test_current_layout_generation_and_build_dependencies(tmp_path):
    tasks = tasks_by_name(make_repo(tmp_path))
    assert set(tasks) == {
        "hardware:identity", "tests:rtl:constants", "tests:rtl:generate", "tests:rtl:random",
        *(f"tests:rtl:{suite}:{stage}" for suite in ("smx", "e2e", "ddr") for stage in ("build", "run", "all")),
        *(f"tests:rtl:{stage}" for stage in ("build", "run", "all")),
    }
    generate = tasks["tests:rtl:generate"]
    case = tmp_path / "tests/hardware/rtl/cases/test1"
    assert str(case / "regfile_c7.mem") in generate["targets"]
    assert str(case / "regfile_c8.mem") not in generate["targets"]
    assert generate["actions"][1][1][0][-4:] == [
        "--num-cores", "8", "--rtl-constants", str(tmp_path / "build/tests/rtl/rtl_constants.txt")]
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
    assert str(rtl_root / "interfaces/AXI4Top.v") not in command
    e2e = tasks["tests:rtl:e2e:build"]["actions"][0][1][0]
    assert str(rtl_root / "interfaces/AXI4Top.v") in e2e
    assert e2e[e2e.index("--top-module") + 1] == "tb_GPGPU_e2e"


def test_every_bench_compiles_the_axi_slave_model_with_its_parameters(tmp_path):
    tasks = tasks_by_name(make_repo(tmp_path))
    test_root = tmp_path / "tests/hardware/rtl"
    model = str(test_root / "AXI4SlaveMemory.sv")
    for suite, bench in (("smx", "tb_GPGPU.sv"), ("e2e", "tb_GPGPU_e2e.sv"), ("ddr", "tb_GPGPU_ddr.sv")):
        build = tasks[f"tests:rtl:{suite}:build"]
        command = build["actions"][0][1][0]
        # The model defines AXI4_SLAVE_CONNECT, so it precedes the bench.
        assert command[-2:] == [model, str(test_root / bench)]
        assert model in build["file_dep"]
        # Headers beside the bench are found with -I and tracked.
        assert f"-I{test_root}" in command
        assert str(test_root / "tb_e2e_host.svh") in build["file_dep"]
        assert "-GAXI_SLAVE_LATENCY_MAX=9" in command


def test_suite_parameters_override_static_and_slave_parameters(tmp_path):
    tasks = tasks_by_name(make_repo(tmp_path))
    smx = tasks["tests:rtl:smx:build"]["actions"][0][1][0]
    ddr = tasks["tests:rtl:ddr:build"]["actions"][0][1][0]
    assert "-GDDR_ENABLE=0" in smx and "-GAXI_SLAVE_SEED=3" in smx
    assert "-GDDR_ENABLE=1" in ddr and "-GDDR_ENABLE=0" not in ddr
    assert "-GAXI_SLAVE_SEED=7" in ddr and "-GAXI_SLAVE_SEED=3" not in ddr


@pytest.mark.parametrize("key", ["tests.rtl.axi_slave.parameters", "tests.rtl.ddr.parameters"])
@pytest.mark.parametrize("value", [{"AXI_SLAVE_SEED": "1"}, {"AXI_SLAVE_SEED": True}, [1]])
def test_hdl_parameter_mappings_must_be_integers(tmp_path, key, value):
    config = make_repo(tmp_path)
    lookup = config.get
    config.get = lambda k: value if k == key else lookup(k)
    with pytest.raises(TypeError, match=key):
        tasks_by_name(config)


def test_expected_results_come_from_the_model_with_rtl_constants(tmp_path):
    tasks = tasks_by_name(make_repo(tmp_path))
    constants = tmp_path / "build/tests/rtl/rtl_constants.txt"
    rtl_root = tmp_path / "hardware/rtl/gpgpu"
    task = tasks["tests:rtl:constants"]
    assert task["targets"] == [str(constants)]
    assert task["actions"][0][1] == [[rtl_root / path for path in (
        "memory/MemoryInterface.sv", "GPGPU.sv", "control/Controller.sv", "interfaces/AXI4Top.v",
        "memory/Memory.sv", "sp/Processor.sv")], rtl_root, constants]
    assert str(rtl_root / "constants.svh") in task["file_dep"]
    generate = tasks["tests:rtl:generate"]
    assert generate["task_dep"] == ["tests:rtl:constants"]
    assert str(constants) in generate["file_dep"]
    assert str(tmp_path / "tools/tests/gpgpu_model.py") in generate["file_dep"]
    random = tasks["tests:rtl:random"]
    assert random["actions"][0][1][0][random["actions"][0][1][0].index("--rtl-constants") + 1] == str(constants)
    assert random["task_dep"] == ["tests:rtl:constants", "tests:rtl:smx:build"]


def test_rtl_constants_file_is_rewritten_only_when_a_value_changes(tmp_path):
    package = tmp_path / "p.sv"
    package.write_text("package p; localparam int unsigned A = 4 * 2; "
                       "typedef enum logic [1:0] {X = 1, Y = 2} e_t; endpackage\n")
    output = tmp_path / "out/rtl_constants.txt"
    rtl.write_rtl_constants([package], tmp_path, output)
    assert output.read_text() == "p::A=8\np::X=1\np::Y=2\n"
    stamp = output.stat().st_mtime_ns
    rtl.write_rtl_constants([package], tmp_path, output)
    assert output.stat().st_mtime_ns == stamp


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


# ----------------------------------------------------------------------
# GPGPU model (expected results)
# ----------------------------------------------------------------------

def model_constants(tmp_path):
    from tools.tests import gpgpu_model
    root = Path(__file__).resolve().parents[3] / "hardware/rtl/gpgpu"
    path = tmp_path / "rtl_constants.txt"
    rtl.write_rtl_constants([root / package for package in (
        "packages/gpu_pkg.sv", "memory/ddr/AXI4FullPkg.sv",
        "memory/ddr/DDRBackendPkg.sv", "memory/MemorySubsystemPkg.sv")], root, path)
    return gpgpu_model.read_constants(path)


def run_model(tmp_path, source, lanes=4, **kwargs):
    from tools.tests import assembler, gpgpu_model
    lines = [line.strip() for line in source.strip().splitlines()]
    labels, instructions = {}, []
    for line in lines:
        if line.endswith(":"):
            labels[line[:-1]] = len(instructions)
        else:
            instructions.append(line)
    program = [assembler.assemble_line(inst, pc, labels) for pc, inst in enumerate(instructions)]
    return gpgpu_model.Warp(program, lanes, model_constants(tmp_path), **kwargs).run(10_000)


def test_model_decodes_what_the_assembler_encodes():
    from tools.tests import assembler, gpgpu_model
    for text, expected in (
        ("addi x5, x6, -3", ("addi", 5, 6, 0, -3)),
        ("sltiu x5, x6, -1", ("sltiu", 5, 6, 0, -1)),
        ("srai x7, x8, 4", ("srai", 7, 8, 0, 4)),
        ("sub x1, x2, x3", ("sub", 1, 2, 3, 0)),
        ("mul x1, x2, x3", ("mul", 1, 2, 3, 0)),
        ("lui x9, 0x18000", ("lui", 9, 0, 0, 0x18000000)),
        ("lw x4, -8(x2)", ("lw", 4, 2, 0, -8)),
        ("sw x4, 2044(x2)", ("sw", 0, 2, 4, 2044)),
        ("bne x1, x2, -12", ("bne", 0, 1, 2, -12)),
        ("jal x1, 2048", ("jal", 1, 0, 0, 2048)),
        ("jalr x0, 0(x1)", ("jalr", 0, 1, 0, 0)),
    ):
        inst = gpgpu_model.decode(assembler.assemble_line(text, 0, {}))
        assert (inst.op, inst.rd, inst.rs1, inst.rs2, inst.imm) == expected, text
    with pytest.raises(gpgpu_model.ModelError, match="unsupported"):
        gpgpu_model.decode(0)


def test_model_lanes_follow_lane_0_and_report_divergence(tmp_path):
    result = run_model(tmp_path, """
        beq x31, x0, skip
        addi x5, x0, 7
        skip:
        addi x6, x0, 1
        jalr x0, 0(x1)
    """)
    # Lane 0 takes the branch, so every lane skips the addi.
    assert [regs[5] for regs in result.regfiles] == [0, 0, 0, 0]
    assert [regs[6] for regs in result.regfiles] == [1, 1, 1, 1]
    assert [regs[31] for regs in result.regfiles] == [0, 1, 2, 3]
    assert result.divergent_pcs == [0]


def test_model_dmem_stores_in_ascending_lane_order(tmp_path):
    result = run_model(tmp_path, """
        addi x5, x31, 10
        sw x5, 64(x0)
        jalr x0, 0(x1)
    """)
    assert result.dmem[16] == 13  # lane 3's store lands last
    assert result.ddr == {} and result.ddr_bursts == 0


def test_model_counts_one_burst_per_group_and_rejects_ambiguous_ddr_stores(tmp_path):
    from tools.tests import gpgpu_model
    result = run_model(tmp_path, """
        lui x5, 0x18000
        slli x6, x31, 6
        add x5, x5, x6
        sw x31, 0(x5)
        jalr x0, 0(x1)
    """)
    # 64 B per lane: lanes 0-1 share the first 128 B group, lanes 2-3 the second.
    assert result.ddr == {0x18000000: 0, 0x18000040: 1, 0x18000080: 2, 0x180000C0: 3}
    assert result.ddr_bursts == 2
    with pytest.raises(gpgpu_model.ModelError, match="unspecified"):
        run_model(tmp_path, """
            lui x5, 0x18000
            sw x31, 0(x5)
            jalr x0, 0(x1)
        """)


def test_model_faults_stop_the_kernel_without_side_effects(tmp_path):
    constants = model_constants(tmp_path)
    result = run_model(tmp_path, """
        addi x5, x0, 9
        lui x6, 0x18000
        lw x7, 0(x6)
        addi x8, x0, 1
        jalr x0, 0(x1)
    """)
    # Framebuffers are write-only: the load faults on every lane.
    assert result.fault.pc == 8
    assert result.fault.lanes == 0b1111
    assert result.fault.statuses == {constants["MemorySubsystemPkg::ST_PERMISSION"]}
    assert [regs[5] for regs in result.regfiles] == [9] * 4
    assert [regs[8] for regs in result.regfiles] == [0] * 4
    unmapped = run_model(tmp_path, """
        lui x6, 0x18000
        sw x0, 0(x6)
        jalr x0, 0(x1)
    """, lanes=1, ddr_enable=False)
    assert unmapped.fault.statuses == {constants["MemorySubsystemPkg::ST_UNMAPPED"]}
