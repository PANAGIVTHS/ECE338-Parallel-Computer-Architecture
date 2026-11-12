"""RtlFlow on Verilator and git: build identity, expected results, benches and random tests."""
from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
from functools import partial
from pathlib import Path

from pydantic import PositiveInt

from gpgpu.api import GpgpuError, Step

from .config import Config, Section
from .design import (architecture, hdl_parameters, identity_path, identity_step, parse_parameters, rtl_root,
                     rtl_sources)
from .tools import run

_FAILURE_MARKERS = ("[FAIL]", "[Error]", "[ERROR]")
_MODEL = Path(__file__).parents[2] / "tests"  # the assembler and GPGPU model scripts


class _Trace(Section):
    enabled: bool
    verilator_flags: list[str]
    dump_file: str


class _AxiSlave(Section):
    source: str
    parameters: dict[str, int]


class _Suite(Section):
    testbench: str
    top: str
    exclude_sources: list[str]
    parameters: dict[str, int]
    plusargs: dict[str, str | int | float]


class _Random(Section):
    iterations: PositiveInt
    seed: int


class _RtlTests(Section):
    trace: _Trace
    range: str
    axi_slave: _AxiSlave
    smx: _Suite
    e2e: _Suite
    ddr: _Suite
    random: _Random


def _range_plusargs(value: str) -> list[str]:
    """An inclusive directed-test range, in the benches' protocol."""
    if value == "all":
        return []
    match = re.fullmatch(r"([1-9][0-9]*)-([1-9][0-9]*)", value)
    if match is None or int(match[1]) > int(match[2]) or int(match[2]) > 2**31 - 1:
        raise GpgpuError(f'tests.rtl.range must be "all" or an inclusive range such as "1-10", not {value!r}')
    return [f"+TEST_IDX={match[1]}", f"+TEST_END={match[2]}"]


def _test_cases(cases: Path) -> list[Path]:
    found = [path for path in cases.iterdir()
             if path.is_dir() and re.fullmatch(r"test\d+", path.name) and (path / "program.asm").is_file()]
    return sorted(found, key=lambda path: int(path.name.removeprefix("test")))


def _write_constants(sources: list[Path], include_directory: Path, output: Path) -> None:
    from .slang import package_constants  # loaded only when constants are really generated

    text = "".join(f"{name}={value}\n" for name, value in sorted(package_constants(sources, include_directory).items()))
    if not output.is_file() or output.read_text(encoding="utf-8") != text:  # regenerate results only on a real change
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")


def _generate(commands: list[list[str]], cwd: Path) -> None:
    for command in commands:
        run(command, cwd=cwd)


def _simulate(command: list[str], cwd: Path, log: Path, env: dict[str, str] | None = None) -> None:
    """Stream a simulation to the terminal and its log, rejecting reported failures."""
    log.parent.mkdir(parents=True, exist_ok=True)
    failed = False
    with log.open("w", encoding="utf-8") as stream:
        process = subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        assert process.stdout is not None
        for line in process.stdout:
            sys.__stdout__.write(line)
            sys.__stdout__.flush()
            stream.write(line)
            stream.flush()
            failed = failed or any(marker in line for marker in _FAILURE_MARKERS)
        status = process.wait()
    if status:
        raise RuntimeError(f"RTL simulator exited with status {status}")
    if failed:
        raise RuntimeError("RTL simulation reported a failure")


def _compile(command: list[str], cwd: Path, build: Path, make: str, identity: Path) -> None:
    """Build a bench. The build identity is read here, not at discovery: it comes from git."""
    command = [*command, *(f"-G{name}={value}" for name, value in parse_parameters(identity.read_text()).items())]
    build.mkdir(parents=True, exist_ok=True)
    # The engine decides whether to rebuild; make must then not reuse objects from other options.
    for pattern in ("*.o", "*.a", "*.gch", "*.gch.d", "main"):
        for artifact in build.glob(pattern):
            artifact.unlink()
    _simulate(command, cwd, build / "build.log", env={**os.environ, "MAKE": make})


def _run_bench(command: list[str], test_root: Path, log: Path, dump: Path) -> None:
    """Keep simulator outputs in the build tree; the bench finds cases/ through a link.

    The previous run's waveform goes first, so a dump that exists is always this run's.
    """
    dump.unlink(missing_ok=True)
    selected = {name: int(arg.split("=", 1)[1]) for arg in command for name in ("+TEST_IDX", "+TEST_END") if arg.startswith(f"{name}=")}
    if len(selected) == 2:
        available = {int(case.name.removeprefix("test")) for case in _test_cases(test_root / "cases")}
        expected = selected["+TEST_IDX"]
        while expected <= selected["+TEST_END"] and expected in available:
            expected += 1
        if expected <= selected["+TEST_END"]:
            raise ValueError(f"tests.rtl.range selects missing test{expected}/program.asm")
    runtime = log.parent
    runtime.mkdir(parents=True, exist_ok=True)
    cases = runtime / "cases"
    if cases.is_symlink() and cases.resolve() != (test_root / "cases").resolve():
        cases.unlink()
    if not cases.is_symlink():
        cases.symlink_to(test_root / "cases", target_is_directory=True)
    _simulate(command, runtime, log)


def _open_waveform(viewer: str, dump: Path) -> None:
    """Start the viewer in its own session and return: the window does not hold the command or its lock."""
    if not dump.is_file():
        raise FileNotFoundError(f"No waveform at {dump}: run the suite with tests.rtl.trace.enabled set to true")
    try:
        subprocess.Popen([viewer, str(dump)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    except FileNotFoundError:
        raise FileNotFoundError(f"Waveform viewer not found: {viewer} (tools.surfer.command)") from None
    print(f"Opened {dump} in {viewer}", flush=True)


class VerilatorFlow:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._s = config.section("tests.rtl", _RtlTests)
        self._range = _range_plusargs(self._s.range)
        self._cores = architecture(config).num_cores
        self._repo = config.repo_root
        self._tests = self._repo / "tests/hardware/rtl"
        self._build = config.build_root / "tests/rtl"
        self._rtl_constants = self._build / "rtl_constants.txt"
        self._python = config.tool("python")
        self._viewer = config.tool("surfer")

    def identity(self) -> Step:
        return identity_step(self._config)

    def constants(self) -> Step:
        # The model takes its constants from the production RTL: the hardware under test.
        sources, headers = rtl_sources(self._config, list(self._config.get("hardware.vivado.exclude_sources")))
        return Step(partial(_write_constants, sources, rtl_root(self._config), self._rtl_constants),
                    inputs=(*sources, *headers), outputs=(self._rtl_constants,))

    def generate(self) -> Step:
        cases = _test_cases(self._tests / "cases")
        seeds = [case / seed for case in cases for seed in ("dmem_seed.mem", "ddr_seed.mem") if (case / seed).is_file()]
        outputs = [output for case in cases for output in (
            case / "program.mem", case / "data.mem", *(case / f"regfile_c{core}.mem" for core in range(self._cores)))]
        assembler, generator = _MODEL / "assembler.py", _MODEL / "expected_generator.py"
        commands = [[self._python, str(assembler)],
                    [self._python, str(generator), "--num-cores", str(self._cores), "--rtl-constants", str(self._rtl_constants)]]
        return Step(partial(_generate, commands, self._tests),
                    inputs=(assembler, generator, _MODEL / "gpgpu_model.py", self._rtl_constants,
                            *(case / "program.asm" for case in cases), *seeds),
                    outputs=outputs, fingerprint={"num_cores": self._cores})

    def _suite(self, suite: str) -> _Suite:
        return getattr(self._s, suite)

    def build_suite(self, suite: str) -> Step:
        settings = self._suite(suite)
        testbench = self._repo / settings.testbench
        slave = self._repo / self._s.axi_slave.source
        sources, headers = rtl_sources(self._config, settings.exclude_sources)
        extensions = self._config.get("hardware.sources.header_extensions")
        bench_headers = sorted(path for path in testbench.parent.iterdir() if path.is_file() and path.suffix in extensions)
        build = self._build / suite
        executable = build / "main"
        parameters = {**hdl_parameters(self._config), **self._s.axi_slave.parameters, **settings.parameters}
        cxx, make = self._config.tool("native_cxx"), self._config.tool("make")
        # Warnings stay non-fatal, except an elaboration-time $fatal: the RTL's parameter checks.
        command = [self._config.tool("verilator"), "--binary", "--timing", "--assert", "--autoflush", "-Wno-fatal",
                   "-Werror-USERFATAL", "--timescale", "1ns/1ps", f"-I{rtl_root(self._config)}", f"-I{testbench.parent}", "-DSIM",
                   "--top-module", settings.top, f"-GNUM_CORES={self._cores}",
                   *(f"-G{name}={value}" for name, value in parameters.items()),
                   "--Mdir", str(build), "-o", executable.name, "-MAKEFLAGS", shlex.join([f"CXX={cxx}", f"LINK={cxx}"]),
                   *(self._s.trace.verilator_flags if self._s.trace.enabled else []),
                   *map(str, sources), str(slave), str(testbench)]
        identity = identity_path(self._config)
        return Step(partial(_compile, command, self._repo, build, make, identity),
                    inputs=(testbench, slave, *sources, *headers, *bench_headers, identity), outputs=(executable,),
                    fingerprint={"command": command, "make": make})

    def run_suite(self, suite: str) -> Step:
        build = self._build / suite
        command = [str(build / "main"), *(f"+{name}={value}" for name, value in self._suite(suite).plusargs.items()),
                   *([f"+DUMP_FILE={self._s.trace.dump_file}"] if self._s.trace.enabled else []), *self._range]
        log = build / "simulation.log"
        return Step(partial(_run_bench, command, self._tests, log, build / self._s.trace.dump_file), outputs=(log,), always_run=True)

    def wave(self, suite: str) -> Step:
        return Step(partial(_open_waveform, self._viewer, self._build / suite / self._s.trace.dump_file), always_run=True)

    def random(self) -> Step:
        build = self._build / "random"
        log = build / "random.log"
        tester = _MODEL / "random_tester.py"
        command = [self._python, str(tester), "--iterations", str(self._s.random.iterations), "--num-cores", str(self._cores),
                   "--rtl-constants", str(self._rtl_constants)]
        if self._s.random.seed != 0:
            command += ["--seed", str(self._s.random.seed)]
        command += ["--python", self._python, "--simulator", str(self._build / "smx/main"), "--test-root", str(self._tests), "--log", str(log)]
        return Step(partial(run, command, cwd=self._repo, creates=build),
                    inputs=(tester, _MODEL / "assembler.py", _MODEL / "expected_generator.py", _MODEL / "gpgpu_model.py", self._rtl_constants),
                    outputs=(log,), always_run=True)
