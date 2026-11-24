"""Facts several adapters share: architecture, RTL files, build identity, output locations."""
from __future__ import annotations

import re
import subprocess
from functools import partial
from pathlib import Path

from pydantic import PositiveInt

from gpgpu.api import GpgpuError, Step

from .config import Config, Section


class Architecture(Section):
    num_cores: PositiveInt
    interface_version: PositiveInt
    ddr_enable: bool


class _Sources(Section):
    extensions: list[str]
    header_extensions: list[str]
    ordered: list[str]


def architecture(config: Config) -> Architecture:
    return config.section("architecture", Architecture)


def rtl_root(config: Config) -> Path:
    root = (config.repo_root / str(config.get("paths.rtl.sources.gpgpu"))).resolve()
    if not root.is_dir():
        raise GpgpuError(f"paths.rtl.sources.gpgpu not found: {root}")
    return root


def rtl_sources(config: Config, exclude: list[str]) -> tuple[list[Path], list[Path]]:
    """(sources, headers) for one consumer: hardware.sources under the RTL root, minus *exclude*.

    Sources start with hardware.sources.ordered, then the rest in path order. An *exclude* entry
    is a bare name matched at any depth (`experimental`) or a path from the root (`sp/ALU.sv`).
    """
    root = rtl_root(config)
    wanted = config.section("hardware.sources", _Sources)
    entries = [tuple(entry.strip("/").split("/")) for entry in exclude]
    names = {entry[0] for entry in entries if len(entry) == 1}
    paths = [entry for entry in entries if len(entry) > 1]

    def collect(extensions: list[str]) -> list[Path]:
        found = []
        for path in sorted(root.rglob("*")):
            parts = path.relative_to(root).parts
            if path.is_file() and path.suffix in extensions and not names & set(parts) \
                    and not any(parts[:len(entry)] == entry for entry in paths):
                found.append(path)
        return found

    found = collect(wanted.extensions)
    for relative in wanted.ordered:
        if not (root / relative).is_file():
            raise GpgpuError(f"hardware.sources.ordered entry not found: {root / relative}")
    first = [root / relative for relative in wanted.ordered if root / relative in found]
    return [*first, *(path for path in found if path not in first)], collect(wanted.header_extensions)


def fabric_clock_mhz(config: Config) -> str:
    value = config.get("hardware.vivado.fabric_clock_mhz")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise GpgpuError("hardware.vivado.fabric_clock_mhz must be a positive number")
    return f"{value:g}"


def hdl_parameters(config: Config) -> dict[str, int]:
    """The build-time GPGPU parameters known from the configuration alone."""
    design = architecture(config)
    return {"INTERFACE_VERSION": design.interface_version,
            "CLOCK_KHZ": round(float(fabric_clock_mhz(config)) * 1000),
            "DDR_ENABLE": int(design.ddr_enable)}


def format_parameters(parameters: dict[str, int]) -> str:
    """NAME=VALUE,NAME=VALUE: one token, safe as a single command argument."""
    return ",".join(f"{name}={value}" for name, value in parameters.items())


def parse_parameters(text: str) -> dict[str, int]:
    parameters: dict[str, int] = {}
    for item in text.strip().split(","):
        match = re.fullmatch(r"([A-Z][A-Z0-9_]*)=([0-9]+)", item)
        if match is None or match[1] in parameters:
            raise ValueError(f"Invalid HDL parameter: {item!r}")
        parameters[match[1]] = int(match[2])
    return parameters


def axi_address(config: Config) -> tuple[str, str]:
    """The GPGPU's CSR aperture. The RTL decodes exactly 64 KiB, so nothing else is valid."""
    values = [config.get(f"hardware.vivado.peripheral.{key}") for key in ("base_address", "range")]
    if not all(isinstance(value, str) and re.fullmatch(r"0[xX][0-9a-fA-F]{1,8}", value) for value in values):
        raise GpgpuError("hardware.vivado.peripheral values must be 32-bit hexadecimal strings")
    base, size = (int(value, 16) for value in values)
    if size != 0x10000 or base % size or base + size > 1 << 32:
        raise GpgpuError("hardware.vivado.peripheral must be a 64-KiB, aligned, 32-bit aperture")
    return f"0x{base:08X}", f"0x{size:08X}"


# Outputs one adapter produces and another consumes.

def identity_path(config: Config) -> Path:
    return config.build_root / "hardware/build_identity.txt"


def _write_identity(git: str, repo: Path, rtl: Path, output: Path) -> None:
    """BUILD_HASH and BUILD_DIRTY: scoped to the RTL, so other commits do not force a resynthesis.

    Rewritten only when it changed, so what depends on the file rebuilds only then.
    """
    def query(*arguments: str) -> str:
        return subprocess.run([git, "-C", str(repo), *arguments, "--", str(rtl)], check=True, capture_output=True, text=True).stdout.strip()

    commit = query("log", "-1", "--format=%H")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError(f"No commit touches {rtl}; BUILD_ID needs one")
    text = format_parameters({"BUILD_HASH": int(commit[:7], 16), "BUILD_DIRTY": int(bool(query("status", "--porcelain")))}) + "\n"
    if not output.is_file() or output.read_text() != text:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text)


def identity_step(config: Config) -> Step:
    output = identity_path(config)
    return Step(partial(_write_identity, config.tool("git"), config.repo_root, rtl_root(config), output),
                outputs=(output,), always_run=True)


def xsa_path(config: Config) -> Path:
    return config.build_root / "hardware/platform" / f"{config.get('hardware.vivado.xsa_name')}.xsa"


def bitstream_path(config: Config) -> Path:
    return config.build_root / "hardware/bitstream" / f"{config.get('hardware.vivado.top')}.bit"


def vitis_workspace(config: Config) -> Path:
    return config.build_root / "software/vitis"


def program_names(config: Config) -> list[str]:
    root = config.repo_root / "software/programs"
    return sorted(path.name for path in root.iterdir() if path.is_dir() and (path / f"{path.name}.c").is_file())


def program_output(config: Config, program: str, suffix: str) -> Path:
    return config.build_root / "software/programs" / program / f"{program}{suffix}"
