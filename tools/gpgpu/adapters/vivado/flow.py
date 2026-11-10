"""HardwareFlow on Vivado: batch Tcl stages under tcl/, each with its own freshness rules."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import uuid
import zipfile
from collections.abc import Callable
from functools import cache, partial
from pathlib import Path
from typing import Annotated, Any, NamedTuple

from pydantic import PositiveFloat, PositiveInt, StringConstraints, model_validator

from gpgpu.api import Action, DesignProject, FreshnessCheck, GpgpuError, Step

from ..config import Config, Section
from ..design import (architecture, axi_address, bitstream_path, fabric_clock_mhz, format_parameters, hdl_parameters,
                      identity_path, identity_step, rtl_sources, xsa_path)
from .ip_project import IpProject, tree_hash
from .package_check import validate_package
from .system_project import SystemProject

TCL = Path(__file__).parent / "tcl"
IP_TOP = "gpgpu_axi"
Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")]
# launch_runs runs each synthesis or implementation in its own process; these hold the real logs.
_RUN_LOG_SUFFIXES = {".log", ".vds", ".vdi", ".rpt"}


class _PhysOpt(Section):
    enabled: bool
    directive: Annotated[str, StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9_]*$")]


class _Peripheral(Section):
    base_address: str
    range: str


class _VendorIp(Section):
    root: str
    exclude: list[str]


class _Vivado(Section):
    ip_project_name: Identifier
    project_name: Identifier
    bd_name: Identifier
    top: Identifier
    xsa_name: Identifier
    version: str
    jobs: PositiveInt
    fabric_clock_mhz: PositiveFloat
    post_route_phys_opt: _PhysOpt
    peripheral: _Peripheral
    exclude_sources: list[str]
    memory_init: str
    vendor_ip: _VendorIp

    @model_validator(mode="after")
    def _consistent_names(self) -> _Vivado:
        if self.top != f"{self.bd_name}_wrapper":
            raise ValueError("top must be <bd_name>_wrapper")
        if self.ip_project_name == self.project_name or {self.ip_project_name, self.project_name} & {"GPU", "ip_repo"}:
            raise ValueError("IP and system project names must differ and cannot be GPU or ip_repo")
        return self


class _Inputs(NamedTuple):
    memory_init: Path
    sources: list[Path]
    headers: list[Path]


def _production_inputs(config: Config, s: _Vivado) -> _Inputs:
    """The IP's files, headers first. The file declaring the top goes last: with a manual compile
    order ipx::package_project takes the last file as the top-level file and parses its ports."""
    rtl, headers = rtl_sources(config, s.exclude_sources)
    declares_top = re.compile(rf"^\s*module\s+{IP_TOP}\b", re.M)
    tops = [path for path in rtl if declares_top.search(path.read_text())]
    if len(tops) != 1:
        raise GpgpuError(f"Exactly one Vivado source must declare module {IP_TOP}; found {tops}")
    memory_init = (config.repo_root / s.memory_init).resolve()
    if not memory_init.is_file():
        raise GpgpuError(f"hardware.vivado.memory_init not found: {memory_init}")
    sources = [*headers, *(path for path in rtl if path != tops[0]), tops[0]]
    names = [path.name for path in (memory_init, *sources)]
    if len(set(names)) != len(names):
        raise GpgpuError("Vivado production inputs resolve to duplicate file names: they are staged flat")
    return _Inputs(memory_init, sources, headers)


def _vendor_ip_dirs(config: Config, s: _Vivado) -> list[Path]:
    """Directories published beside the GPGPU in the IP repository."""
    root = (config.repo_root / s.vendor_ip.root).resolve()
    if not root.is_dir():
        raise GpgpuError(f"hardware.vivado.vendor_ip.root not found: {root}")
    return sorted(path for path in root.iterdir()
                  if path.is_dir() and not path.name.startswith(".") and path.name not in s.vendor_ip.exclude)


def _write_manifest(path: Path, inputs: _Inputs) -> None:
    """The IP inputs as `<kind>\\t<path>` lines. A file, because long lists do not survive -tclargs."""
    rows = [("memory", inputs.memory_init), *(("source", p) for p in inputs.sources), *(("header", p) for p in inputs.headers)]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{kind}\t{p}\n" for kind, p in rows))


def _check_managed(directory: Path, name: str, part: str, kind: str) -> None:
    """Refuse a project this flow did not create. Nothing is ever adopted or deleted."""
    if directory.is_symlink():
        raise RuntimeError(f"Refusing symbolic-link project: {directory}")
    if not directory.exists():
        return
    marker = directory / ".gpgpu-managed.json"
    if not directory.is_dir() or marker.is_symlink() or not marker.is_file():
        raise RuntimeError(f"Protected/unmanaged project {directory}; use a fresh paths.build.root.")
    if json.loads(marker.read_text()) != {"project": name, "part": part, "kind": kind, "schema": 1}:
        raise RuntimeError(f"Incompatible managed project identity: {directory}")


def _prepare_managed(directory: Path, name: str, part: str, kind: str, recreate: bool = False) -> None:
    _check_managed(directory, name, part, kind)
    if directory.exists() and recreate:  # the previous project stays recoverable
        snapshots = directory.parent / ".snapshots"
        snapshots.mkdir(exist_ok=True)
        directory.rename(snapshots / f"{name}-{uuid.uuid4().hex}")
    directory.mkdir(parents=True, exist_ok=True)
    marker = directory / ".gpgpu-managed.json"
    if not marker.exists():
        marker.write_text(json.dumps({"project": name, "part": part, "kind": kind, "schema": 1}, sort_keys=True) + "\n")


def _check_saved_bd(path: Path, part: str) -> None:
    design = json.loads(path.read_text())["design"]
    cells = design["components"]
    if design["design_info"].get("name") != path.stem or design["design_info"].get("device") != part:
        raise RuntimeError(f"Incompatible saved BD identity: {path}")
    if cells.get("gpgpu_axi_0", {}).get("vlnv") != "user.org:user:gpgpu_axi:1.0":
        raise RuntimeError(f"Saved BD is not the packaged AXI system: {path}")
    if not {"processing_system7_0", "gpgpu_ctrl"} <= cells.keys() or any("axi_gpio" in name for name in cells):
        raise RuntimeError(f"Legacy/incomplete saved BD: {path}")


@cache  # about a second per call, and every stage's freshness check asks
def _check_tool(command: str, required: str) -> None:
    result = subprocess.run([command, "-version"], capture_output=True, text=True, check=True)
    if re.search(rf"(?<!\d){re.escape(required)}(?!\d)", result.stdout + result.stderr) is None:
        raise RuntimeError(f"Vivado {required} required: {result.stdout}{result.stderr}")


def _tool_current(command: str, required: str) -> bool:
    _check_tool(command, required)
    return True


def _stage_name(command: list[str]) -> str:
    return Path(command[command.index("-source") + 1]).stem


def _run_vivado(command: list[str], cwd: Path, project: Path) -> None:
    """One batch stage, streamed live and into the managed project's own logs."""
    logs = project / ".gpgpu/logs"
    logs.mkdir(parents=True, exist_ok=True)
    stage = _stage_name(command)
    argv = [command[0], "-log", str(logs / f"{stage}.log"), "-journal", str(logs / f"{stage}.jou"), *command[1:]]
    process = subprocess.Popen(argv, cwd=project, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    assert process.stdout is not None
    with (logs / f"{stage}.console.log").open("w") as log:
        for line in process.stdout:
            print(line, end="", flush=True)
            log.write(line)
            log.flush()
    if process.wait():
        raise RuntimeError(f"Vivado stage {stage} failed with exit {process.returncode}; see {logs}")


def _create_ip(command: list[str], repo: Path, directory: Path, name: str, part: str, version: str, inputs: _Inputs) -> None:
    _check_tool(command[0], version)
    _prepare_managed(directory, name, part, "ip", recreate=True)
    _write_manifest(Path(command[command.index("-sources-manifest") + 1]), inputs)
    _run_vivado(command, repo, directory)
    if not (directory / f"{name}.xpr").is_file():
        raise RuntimeError("IP creation did not produce the development project")


def _package_current(directory: Path, inputs: _Inputs) -> bool:
    """A completion stamp is valid only for the complete, independently valid tree."""
    try:
        metadata = json.loads((directory / ".gpgpu-package.json").read_text())
        if metadata.get("revision", 0) < 1 or metadata.get("files") != tree_hash(directory):
            return False
        validate_package(directory, *inputs)
    except (OSError, ValueError, RuntimeError):
        return False
    return True


def _package_ip(command: list[str], repo: Path, project: Path, xpr: Path, ip_repo: Path, inputs: _Inputs, vendor_dirs: list[Path]) -> None:
    """Package into staging, validate, then swap. The live repository stays valid throughout."""
    stamp = ip_repo / ".gpgpu-package.json"
    if ip_repo.exists() and any(ip_repo.iterdir()) and not stamp.is_file():
        raise RuntimeError(f"Protected/unmanaged IP repository: {ip_repo}; use a fresh build root")
    staging = ip_repo.parent / f".ip-package-{uuid.uuid4().hex}"
    staging.mkdir(parents=True)
    command = list(command)
    command[command.index("-ip-repo-dir") + 1] = str(staging)
    previous = json.loads(stamp.read_text()) if stamp.exists() else {}
    revision = int(previous.get("revision", 0)) + 1
    if revision > 0x7FFFFFFF:
        raise ValueError("IP core revision exhausted; cannot refresh same VLNV safely")
    command += ["-ip-revision", str(revision)]
    _write_manifest(Path(command[command.index("-sources-manifest") + 1]), inputs)
    _run_vivado(command, repo, project)
    for source in vendor_dirs:
        if (staging / source.name).exists():
            raise RuntimeError(f"Vendor IP {source.name} collides with the packaged GPGPU in {staging}")
        shutil.copytree(source, staging / source.name, symlinks=False)
    validate_package(staging, *inputs)
    (staging / ".gpgpu-package.json").write_text(
        json.dumps({"revision": revision, "files": tree_hash(staging)}, sort_keys=True, indent=2) + "\n")
    old = None
    if ip_repo.exists():
        old = ip_repo.parent / f".ip-repo-snapshot-{uuid.uuid4().hex}"
        ip_repo.rename(old)
    try:
        staging.rename(ip_repo)
    except BaseException:
        if old is not None:
            old.rename(ip_repo)
        raise
    # The project must open the published package, not the staging folder that just moved.
    xpr.write_text(xpr.read_text().replace(staging.name, ip_repo.name))


def _saved_current(directory: Path, name: str, part: str, bd: Path) -> bool:
    """Validate the saved state even when the outputs otherwise look up to date."""
    _check_managed(directory, name, part, "system")
    if bd.exists():
        _check_saved_bd(bd, part)
    return True


def _create_system(command: list[str], repo: Path, directory: Path, name: str, part: str, bd: Path, wrapper: Path,
                   ip_repo: Path, version: str, inputs: _Inputs) -> None:
    _check_tool(command[0], version)
    validate_package(ip_repo, *inputs)
    if not (ip_repo / ".gpgpu-package.json").is_file():
        raise RuntimeError("IP repository has no completed managed publication")
    _prepare_managed(directory, name, part, "system")
    saved = sorted(directory.rglob("*.bd"))
    if saved and not bd.is_file():
        raise RuntimeError("Configured BD is missing; refusing to replace saved designs: " + ", ".join(map(str, saved)))
    if bd.is_file():
        _check_saved_bd(bd, part)
        snapshots = directory / ".gpgpu/bd-snapshots"
        snapshots.mkdir(parents=True, exist_ok=True)
        shutil.copy2(bd, snapshots / f"{bd.stem}-{uuid.uuid4().hex}.bd")
    _run_vivado(command, repo, directory)
    if not (directory / f"{name}.xpr").is_file() or not bd.is_file() or not wrapper.is_file():
        raise RuntimeError("System creation did not produce project, BD and wrapper")
    _check_saved_bd(bd, part)


def _collect_run_logs(directory: Path, stage: str, runs: tuple[str, ...]) -> None:
    """Copy the stage's run logs to .gpgpu/logs/<stage>/<run>/, keeping only the current runs."""
    destination = directory / ".gpgpu/logs" / stage
    if destination.exists():
        shutil.rmtree(destination)
    for run in sorted({path for pattern in runs for path in directory.glob(f"*.runs/{pattern}") if path.is_dir()}):
        for path in sorted(run.iterdir()):
            if path.is_file() and path.suffix in _RUN_LOG_SUFFIXES:
                (destination / run.name).mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination / run.name / path.name)


def _run_stage(command: list[str], repo: Path, directory: Path, target: Path, xsa: bool = False, runs: tuple[str, ...] = ()) -> None:
    try:
        _run_vivado(command, repo, directory)
    finally:
        _collect_run_logs(directory, _stage_name(command), runs)  # also on failure: they hold the error
    if not target.is_file() or target.stat().st_size == 0:
        raise RuntimeError(f"Vivado did not produce {target}")
    if xsa:
        with zipfile.ZipFile(target) as archive:
            files = archive.namelist()
        if not (any(f.endswith(".bit") for f in files) and any(f.endswith(".hwh") for f in files)
                and {"ps7_init.tcl", "ps7_init.c"} <= {Path(f).name for f in files}):
            raise RuntimeError(f"XSA lacks bitstream/handoff/PS init: {files}")


def timing_summary(run_dir: Path) -> tuple[str, dict[str, float]] | None:
    """The design timing summary impl_1 reported last: after post-route phys_opt when it ran,
    else after routing. None when neither report exists."""
    for suffix in ("_timing_summary_postroute_physopted.rpt", "_timing_summary_routed.rpt"):
        for report in sorted(run_dir.glob(f"*{suffix}")):
            lines = report.read_text(errors="replace").splitlines()
            for index, line in enumerate(lines[:-2]):
                if line.split()[:2] == ["WNS(ns)", "TNS(ns)"]:
                    v = lines[index + 2].split()
                    return report.name, {"wns": float(v[0]), "tns": float(v[1]), "failing": int(v[2]),
                                         "whs": float(v[4]), "ths": float(v[5]), "hold_failing": int(v[6])}
    return None


def _implement(command: list[str], repo: Path, directory: Path, target: Path) -> None:
    """Implementation, then the timing it closed: a design that misses timing still builds."""
    _run_stage(command, repo, directory, target, runs=("impl_1",))
    found = timing_summary(target.parent)
    if found is None:
        print(f"WARNING: impl_1 wrote no timing summary in {target.parent}", flush=True)
        return
    report, t = found
    print(f"Timing ({report}): setup WNS {t['wns']:.3f} ns, TNS {t['tns']:.3f} ns over {t['failing']:.0f} endpoints;"
          f" hold WHS {t['whs']:.3f} ns, THS {t['ths']:.3f} ns over {t['hold_failing']:.0f} endpoints", flush=True)
    if t["wns"] < 0 or t["whs"] < 0:
        print("WARNING: the design does not meet timing, so the bitstream may misbehave on the board", flush=True)


class _Probe(NamedTuple):
    """StateProbe for files a stage cannot declare as inputs: they do not exist at first
    discovery, or the stage rewrites them. Saved after the stage, so its own writes do not count."""

    key: str
    state: Callable[[], object]


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""


def _generated_ip(project: Path) -> dict[str, str]:
    return {path.relative_to(project).as_posix(): _digest(path)
            for path in sorted(project.rglob("*.xci")) if ".gpgpu" not in path.parts}


def _run_settings(xpr: Path, run: str) -> str:
    """What the GUI can change about a run. Every stage rewrites the rest of the .xpr."""
    found = re.search(rf'<Run Id="{run}".*?</Run>', xpr.read_text(), re.S) if xpr.is_file() else None
    return re.sub(r' (State|LaunchOptions)="[^"]*"', "", found[0]) if found else ""


class VivadoFlow:
    def __init__(self, config: Config) -> None:
        s = self._s = config.section("hardware.vivado", _Vivado)
        self._config = config
        self._repo = config.repo_root
        vivado = config.build_root / "hardware/vivado"
        self._ip_dir, self._system, self._ip_repo = vivado / s.ip_project_name, vivado / s.project_name, vivado / "ip_repo"
        self._ip_xpr = self._ip_dir / f"{s.ip_project_name}.xpr"
        self._xpr = self._system / f"{s.project_name}.xpr"
        self._bd = self._system / f"{s.project_name}.srcs/sources_1/bd/{s.bd_name}/{s.bd_name}.bd"
        self._wrapper = self._system / f"{s.project_name}.gen/sources_1/bd/{s.bd_name}/hdl/{s.top}.v"
        self._synth = self._system / f"{s.project_name}.runs/synth_1/{s.top}.dcp"
        self._route = self._system / f"{s.project_name}.runs/impl_1/{s.top}_routed.dcp"
        self._bit, self._xsa = bitstream_path(config), xsa_path(config)
        self._stamp, self._component = self._ip_repo / ".gpgpu-package.json", self._ip_repo / "component.xml"
        self._xdc = self._repo / "hardware/constraints/smart_zynq.xdc"
        self._script = self._repo / "hardware/bd" / f"{s.bd_name}.tcl"
        self._identity = identity_path(config)
        self._part = str(config.get("hardware.fpga.part"))
        self._vivado = config.tool("vivado")
        self._inputs = _production_inputs(config, s)
        self._vendor_dirs = _vendor_ip_dirs(config, s)
        self._base, self._range = axi_address(config)
        self._cores = architecture(config).num_cores
        self._fclk = fabric_clock_mhz(config)
        self._parameters = format_parameters(hdl_parameters(config))
        self._source_deps = (self._inputs.memory_init, *self._inputs.sources)
        # Everything every stage depends on, including this code and the Vivado install itself.
        executable = shutil.which(self._vivado)
        self._shared = (TCL / "common.tcl", Path(__file__), Path(__file__).parents[1] / "design.py",
                        *([Path(executable).resolve()] if executable else []))
        self._system_project = SystemProject(
            vivado=self._vivado, repo=self._repo, directory=self._system, xpr=self._xpr, bd=self._bd, ip_repo=self._ip_repo,
            part=self._part, script=self._script, top=s.top, cores=self._cores, base=self._base, size=self._range, fclk=self._fclk)
        self._ip_project = IpProject(vivado=self._vivado, repo=self._repo, directory=self._ip_dir, xpr=self._ip_xpr, ip_repo=self._ip_repo,
                                     inputs=self._source_deps, recreate=self._create_ip_action())

    def projects(self) -> list[DesignProject]:
        return [self._ip_project, self._system_project]

    def _command(self, script: str, *, ip: bool = False) -> list[str]:
        s = self._s
        values: dict[str, Any] = {
            "project-dir": self._ip_dir if ip else self._system, "project-name": s.ip_project_name if ip else s.project_name,
            "part": self._part, "bd-name": s.bd_name, "top": IP_TOP if ip else s.top,
            "sources-manifest": self._ip_dir / ".gpgpu/sources.tsv", "xdc-file": self._xdc, "bitstream-dir": self._bit.parent,
            "platform-dir": self._xsa.parent, "xsa-name": self._xsa.stem, "bd-script": self._script, "num-cores": self._cores,
            "hdl-parameters": self._parameters, "build-identity": self._identity, "jobs": s.jobs, "repo-root": self._repo,
            "ip-repo-dir": self._ip_repo, "axi-base": self._base, "axi-range": self._range, "fclk0-mhz": self._fclk,
            "post-route-phys-opt": int(s.post_route_phys_opt.enabled),
            "post-route-phys-opt-directive": s.post_route_phys_opt.directive, "flow-version": s.version}
        return [self._vivado, "-mode", "batch", "-source", str(TCL / script), "-tclargs",
                *(item for key, value in values.items() for item in (f"-{key}", str(value)))]

    def _stage(self, script: str, action: Action, deps: tuple[Path, ...], outputs: tuple[Path, ...], *,
               command: list[str], fingerprint: dict[str, Any] | None = None, checks: tuple[FreshnessCheck, ...] = ()) -> Step:
        return Step(action, inputs=(*self._shared, TCL / script, *deps), outputs=outputs,
                    fingerprint={"command": command, **(fingerprint or {})},
                    checks=(partial(_tool_current, self._vivado, self._s.version), *checks))

    def _create_ip_action(self) -> Action:
        return partial(_create_ip, self._command("create_ip_project.tcl", ip=True), self._repo, self._ip_dir,
                       self._s.ip_project_name, self._part, self._s.version, self._inputs)

    def identity(self) -> Step:
        return identity_step(self._config)

    def create_ip(self) -> Step:
        return self._stage("create_ip_project.tcl", self._ip_project.recording_baseline(self._create_ip_action()),
                           (*self._source_deps, TCL / "production_sources.tcl", self._identity), (self._ip_xpr,),
                           command=self._command("create_ip_project.tcl", ip=True))

    def package_ip(self) -> Step:
        command = self._command("package_ip.tcl", ip=True)
        vendor_files = [path for directory in self._vendor_dirs for path in sorted(directory.rglob("*")) if path.is_file()]
        return self._stage(
            "package_ip.tcl", partial(_package_ip, command, self._repo, self._ip_dir, self._ip_xpr, self._ip_repo, self._inputs, self._vendor_dirs),
            (self._ip_xpr, *self._source_deps, TCL / "production_sources.tcl", Path(__file__).with_name("package_check.py"),
             TCL / "ip/xgui/gpgpu_axi_v1_0.tcl", self._identity, *vendor_files),
            (self._component, self._stamp), command=command,
            # A removed vendor directory leaves no changed file behind; its name does.
            fingerprint={"vendor_ip": [directory.name for directory in self._vendor_dirs]},
            checks=(partial(_package_current, self._ip_repo, self._inputs),))

    def create_system(self) -> Step:
        s = self._s
        command = self._command("create_system.tcl")
        action = partial(_create_system, command, self._repo, self._system, s.project_name, self._part, self._bd, self._wrapper,
                         self._ip_repo, s.version, self._inputs)
        return self._stage("create_system.tcl", self._system_project.keeping_baseline(action),
                           (self._component, self._stamp, self._script, TCL / "configure_block_design.tcl", self._xdc),
                           (self._xpr, self._bd, self._wrapper), command=command,
                           # A design edited in the GUI is validated, wrapped and overlaid here before it is built.
                           checks=(partial(_saved_current, self._system, s.project_name, self._part, self._bd),
                                   _Probe("block_design", partial(_digest, self._bd))))

    def synthesize(self) -> Step:
        command = self._command("synthesis.tcl")
        return self._stage("synthesis.tcl", partial(_run_stage, command, self._repo, self._system, self._synth, runs=("*synth_1",)),
                           # Not the .xpr: every later stage rewrites it, so synthesis would never be fresh.
                           (self._bd, self._wrapper, self._stamp, self._xdc, *self._source_deps), (self._synth,),
                           command=command, checks=(_Probe("generated_ip", partial(_generated_ip, self._system)),
                                                    _Probe("run_settings", partial(_run_settings, self._xpr, "synth_1"))))

    def implement(self) -> Step:
        command = self._command("implementation.tcl")
        return self._stage("implementation.tcl", partial(_implement, command, self._repo, self._system, self._route),
                           (self._synth, self._bd, self._xdc), (self._route,), command=command,
                           checks=(_Probe("run_settings", partial(_run_settings, self._xpr, "impl_1")),))

    def bitstream(self) -> Step:
        command = self._command("bitstream.tcl")
        return self._stage("bitstream.tcl", partial(_run_stage, command, self._repo, self._system, self._bit, runs=("impl_1",)),
                           (self._route, self._xdc), (self._bit,), command=command)

    def export_hardware(self) -> Step:
        command = self._command("export_hardware.tcl")
        return self._stage("export_hardware.tcl", partial(_run_stage, command, self._repo, self._system, self._xsa, xsa=True),
                           (self._bit, self._route, self._bd, self._stamp), (self._xsa,), command=command)
