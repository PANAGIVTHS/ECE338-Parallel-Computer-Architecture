"""PlatformFlow on Vitis: vendor_flow.py does the work, inside Vitis's own Python."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import zipfile
from functools import partial
from pathlib import Path
from tempfile import NamedTemporaryFile

from gpgpu.api import Step

from ..config import Config, Section
from ..design import axi_address, vitis_workspace, xsa_path

_VENDOR_FLOW = Path(__file__).with_name("vendor_flow.py")
_TEXT_SUFFIXES = {"", ".c", ".cmake", ".h", ".ini", ".json", ".ld", ".md", ".py", ".tcl", ".txt", ".yaml", ".yml"}
_EXCLUDED_SUFFIXES = {".a", ".bit", ".d", ".elf", ".log", ".o", ".obj", ".xsa"}
_EXCLUDED_PARTS = {".Xil", ".lock", ".vitisWorkspace.json", "__pycache__", "build", "build_configs", "CMakeFiles", "export", "logs"}


class _Vitis(Section):
    version: str
    platform_name: str
    host_name: str
    cpu: str
    domain: str
    os: str
    template: str
    default_archive: str
    host_sources: list[str]


def _run_vitis(command: list[str], repo: Path, outputs: tuple[Path, ...]) -> None:
    subprocess.run(command, cwd=repo, check=True)
    missing = [str(path) for path in outputs if not path.is_file()]
    if missing:
        raise FileNotFoundError("Vitis completed without producing: " + ", ".join(missing))


class _EditableHost:
    """StateProbe of the SDK-created editable inputs, saved after the build.

    Declaring them as inputs would force a second build: they do not exist at first discovery.
    """

    key = "editable_host_digest"

    def __init__(self, root: Path) -> None:
        self.root = root

    def state(self) -> str:
        inputs = [self.root / "UserConfig.cmake", self.root / "src/UserConfig.cmake"]
        inputs += [path for path in (self.root / "src").rglob("*") if path.suffix in {".c", ".h", ".cpp", ".hpp"}]
        digest = hashlib.sha256()
        for path in sorted(inputs):
            if path.is_file():
                digest.update(str(path.relative_to(self.root)).encode() + b"\0" + path.read_bytes() + b"\0")
        return digest.hexdigest()


def _component(path: Path, name: str) -> dict:
    metadata = json.loads(path.read_text(encoding="utf-8"))
    if metadata.get("name") != name:
        raise ValueError(f"Vitis component at {path} is not named {name!r}")
    return metadata


def _portable(text: str, repo: Path, workspace: Path, xsa: Path, vendor: str | None) -> str:
    """Replace this machine's paths with the markers vendor_flow.py restores."""
    pairs = [(str(xsa.resolve()), "${GPGPU_XSA}"), (str(workspace), "${GPGPU_WORKSPACE}"), (str(repo), "${GPGPU_REPO_ROOT}")]
    if vendor:
        pairs += [(vendor, "${XILINX_VITIS}"), (str(Path(vendor).parent), "${XILINX_VITIS}/..")]
    for absolute, marker in sorted(pairs, key=lambda pair: len(pair[0]), reverse=True):
        text = text.replace(absolute, marker)
    return text


def _vendor_root(host: Path) -> str | None:
    app = host / "src/app.yaml"
    match = re.search(r"(?m)^app_src_dir:\s*(.+?)/data/embeddedsw(?:/|$)", app.read_text(encoding="utf-8")) if app.is_file() else None
    return match[1] if match and not match[1].startswith("${") else None


def _excluded(relative: Path) -> bool:
    if any(part in _EXCLUDED_PARTS for part in relative.parts):
        return True
    # An SDK-owned input, not a compiled output: FSBL needs it.
    return relative.parts[-4:] != ("libsrc", "xilrsa", "src", "librsa.a") and relative.suffix.lower() in _EXCLUDED_SUFFIXES


def _export(workspace: Path, archive: Path, repo: Path, platform: str, host: str) -> None:
    """Atomically replace the archive with the editable state. Hardware is never exported."""
    roots = {platform: workspace / platform, host: workspace / host}
    metadata_path = roots[platform] / "vitis-comp.json"
    metadata = _component(metadata_path, platform)
    _component(roots[host] / "vitis-comp.json", host)
    xsa = Path(metadata["configuration"].get("xsa") or repo / "missing.xsa")
    vendor = _vendor_root(roots[host])
    with NamedTemporaryFile(prefix=f".{archive.name}.", suffix=".tmp", dir=archive.parent, delete=False) as temporary:
        temporary_path = Path(temporary.name)
    try:
        with zipfile.ZipFile(temporary_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as output:
            for name, root in roots.items():
                for path in sorted(root.rglob("*")):
                    if path.is_symlink():
                        raise ValueError(f"Refusing to export symbolic link: {path}")
                    relative = path.relative_to(root)
                    if not path.is_file() or _excluded(relative):
                        continue
                    data = path.read_bytes()
                    if path.suffix.lower() in _TEXT_SUFFIXES:
                        try:
                            text = data.decode("utf-8")
                        except UnicodeDecodeError:
                            pass
                        else:
                            if path == metadata_path:
                                portable = json.loads(text)
                                portable["configuration"].update(xsa="${GPGPU_XSA}", xsaPathInPlatform=f"{platform}/hw/{platform}.xsa")
                                text = json.dumps(portable, indent=2, ensure_ascii=False) + "\n"
                            data = _portable(text, repo, workspace, xsa, vendor).encode("utf-8")
                    if any(marker in data.lower() for marker in (b"/home/", b"/workspace/")):
                        raise ValueError(f"Refusing to export machine-specific path data in {path}")
                    # Fixed date and mode, so an unchanged project gives an identical archive.
                    info = zipfile.ZipInfo((Path(name) / relative).as_posix(), date_time=(1980, 1, 1, 0, 0, 0))
                    info.compress_type, info.external_attr = zipfile.ZIP_DEFLATED, 0o100644 << 16
                    output.writestr(info, data, compresslevel=9)
        if archive.is_file() and archive.read_bytes() == temporary_path.read_bytes():
            print(f"Portable Vitis default project is already current: {archive}", file=sys.stderr)
        else:
            os.replace(temporary_path, archive)
            print(f"Updated portable Vitis default project: {archive}", file=sys.stderr)
        for root in roots.values():
            (root / "vitis-comp.json").touch()
    finally:
        temporary_path.unlink(missing_ok=True)


class VitisFlow:
    def __init__(self, config: Config) -> None:
        s = self._s = config.section("hardware.vitis", _Vitis)
        self._repo = config.repo_root
        self._workspace = vitis_workspace(config)
        self._archive = self._repo / s.default_archive
        self._xsa = xsa_path(config)
        self._base, self._range = axi_address(config)
        self._prefix = [config.tool("vitis"), "-s", str(_VENDOR_FLOW), "--"]
        platform, host = self._workspace / s.platform_name, self._workspace / s.host_name
        self._platform_metadata, self._host_metadata = platform / "vitis-comp.json", host / "vitis-comp.json"
        export = platform / "export" / s.platform_name
        self._platform_outputs = (export / f"hw/{s.platform_name}.xsa", export / "hw/sdt/ps7_init.tcl", export / f"{s.platform_name}.xpfm")
        self._elf = host / f"build/{s.host_name}.elf"
        self._host_root = host

    def create_project(self) -> Step:
        s = self._s
        command = [*self._prefix, "project", "--workspace", str(self._workspace), "--xsa", str(self._xsa),
                   "--platform", s.platform_name, "--cpu", s.cpu, "--os", s.os, "--domain", s.domain]
        return Step(partial(_run_vitis, command, self._repo, (self._platform_metadata,)),
                    inputs=(self._xsa, _VENDOR_FLOW), outputs=(self._platform_metadata,),
                    fingerprint={"version": s.version, "command": command})

    def build_platform(self) -> Step:
        command = [*self._prefix, "build", "--workspace", str(self._workspace), "--component", self._s.platform_name]
        return Step(partial(_run_vitis, command, self._repo, self._platform_outputs),
                    inputs=(_VENDOR_FLOW, self._platform_metadata, self._xsa), outputs=self._platform_outputs,
                    fingerprint={"command": command})

    def build_host(self) -> Step:
        s = self._s
        sources = [self._repo / relative for relative in s.host_sources]
        headers = sorted({header for source in sources for header in source.parent.glob("*.h")})
        command = [*self._prefix, "host", "--workspace", str(self._workspace), "--component", s.host_name,
                   "--platform", s.platform_name, "--domain", s.domain, "--template", s.template, "--base-address", self._base,
                   "--archive", str(self._archive), "--repo-root", str(self._repo)]
        command += [argument for source in sources for argument in ("--source", str(source))]
        outputs = (self._elf, self._host_metadata)
        return Step(partial(_run_vitis, command, self._repo, outputs),
                    inputs=(_VENDOR_FLOW, self._archive, *self._platform_outputs, *sources, *headers), outputs=outputs,
                    fingerprint={"command": command, "range": self._range}, checks=(_EditableHost(self._host_root),))

    def export_project(self) -> Step:
        return Step(partial(_export, self._workspace, self._archive, self._repo, self._s.platform_name, self._s.host_name),
                    always_run=True)
