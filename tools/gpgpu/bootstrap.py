"""Composition root: the one place that knows which adapter implements which port."""
from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Iterable
from functools import cache
from pathlib import Path
from typing import Any

import gpgpu.plugins
from gpgpu.api import Board, HardwareFlow, PlatformFlow, PluginFailure, RtlFlow, Toolchain
from gpgpu.app.registry import Registry
from gpgpu.app.workspace import Workspace

REPO_ROOT = Path(__file__).resolve().parents[2]

# Imported on first use, so a broken adapter only costs the commands that need it.
_BACKENDS = {
    HardwareFlow: "gpgpu.adapters.vivado.flow:VivadoFlow",
    PlatformFlow: "gpgpu.adapters.vitis.flow:VitisFlow",
    RtlFlow: "gpgpu.adapters.verilator:VerilatorFlow",
    Toolchain: "gpgpu.adapters.gcc:GccToolchain",
    Board: "gpgpu.adapters.board.ssh:SshBoard",
}


def _load(path: str) -> Any:
    module, _, name = path.partition(":")
    return getattr(importlib.import_module(module), name)


@cache
def load_registry() -> Registry:
    """Every module in gpgpu/plugins is a category. Adding a file is all it takes."""
    plugins, failures = {}, []
    for info in pkgutil.iter_modules(gpgpu.plugins.__path__):
        try:
            plugins[info.name] = importlib.import_module(f"gpgpu.plugins.{info.name}")
        except Exception as error:
            failures.append(PluginFailure(info.name, f"{type(error).__name__}: {error}"))
    return Registry(plugins, failures)


def open_workspace(*, profile: str = "default", overrides: Iterable[str] = (), repo_root: Path = REPO_ROOT) -> Workspace:
    config = _load("gpgpu.adapters.config:Config")(repo_root, profile, overrides)
    backend = cache(lambda port: _load(_BACKENDS[port])(config))
    return Workspace(config, load_registry(), backend, _load("gpgpu.adapters.doit_engine:DoitEngine")(config),
                     _load("gpgpu.adapters.tools:Machine")(config))
