"""Layered configuration: default profile, selected profile, config/local.yaml, then --set."""
from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from functools import cached_property
from pathlib import Path
from typing import Any, TypeVar

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from gpgpu.api import GpgpuError

_MISSING = object()
_PROTECTED = (".git", "config", "docs", "hardware", "software", "tests", "tools")
M = TypeVar("M", bound=BaseModel)


class Section(BaseModel):
    """Base of every adapter's settings. An unknown key is a typo, not an option."""

    model_config = ConfigDict(extra="forbid", frozen=True)


def _load(path: Path) -> dict[str, Any]:
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    except yaml.YAMLError as error:
        raise GpgpuError(f"Invalid YAML in {path}: {error}") from None
    if not isinstance(loaded or {}, dict):
        raise GpgpuError(f"Configuration root must be a mapping: {path}")
    return loaded or {}


def _merge(target: dict[str, Any], incoming: dict[str, Any], source: str, sources: dict[str, str], prefix: str = "") -> None:
    """Merge one layer into target, recording which layer set each leaf."""
    for key, value in incoming.items():
        if isinstance(value, dict):
            if not isinstance(target.get(key), dict):
                target[key] = {}
            _merge(target[key], value, source, sources, f"{prefix}{key}.")
        else:
            target[key] = value
            sources[f"{prefix}{key}"] = source


class Config:
    """One invocation's resolved configuration, and where each value came from."""

    def __init__(self, repo_root: Path, profile: str = "default", overrides: Iterable[str] = ()) -> None:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", profile):
            raise GpgpuError(f"Invalid profile name: {profile!r}")
        self.repo_root, self.profile = repo_root, profile
        self._values: dict[str, Any] = {}
        self._sources: dict[str, str] = {}
        default, selected = "config/profiles/default.yaml", f"config/profiles/{profile}.yaml"
        if not (repo_root / selected).is_file():
            raise GpgpuError(f"Profile not found: {selected}")
        self._default = _load(repo_root / default)
        for layer in dict.fromkeys((default, selected, "config/local.yaml")):
            _merge(self._values, _load(repo_root / layer), layer, self._sources)
        for override in overrides:
            self._override(override)

    def _override(self, item: str) -> None:
        key, separator, raw = item.partition("=")
        if not separator or not key:
            raise GpgpuError(f"Invalid --set value {item!r}; expected OPTION=VALUE")
        self.get(key)  # a typo is an error, not a new option
        try:
            value = yaml.safe_load(raw)
        except yaml.YAMLError as error:
            raise GpgpuError(f"Invalid YAML value in --set {item!r}: {error}") from None
        *parents, leaf = key.split(".")
        target = self._values
        for part in parents:
            target = target[part]
        _merge(target, {leaf: value}, "--set", self._sources, "".join(f"{part}." for part in parents))

    def get(self, key: str, default: Any = _MISSING) -> Any:
        current: Any = self._values
        for part in key.split("."):
            if not isinstance(current, dict) or part not in current:
                if default is _MISSING:
                    raise GpgpuError(f"Unknown configuration option: {key}")
                return default
            current = current[part]
        return current

    def source_of(self, key: str) -> str:
        if key not in self._sources:
            raise GpgpuError(f"No source recorded for configuration option: {key}")
        return self._sources[key]

    def section(self, key: str, model: type[M]) -> M:
        """A validated section. Errors name the key and where it was set."""
        try:
            return model.model_validate(self.get(key))
        except ValidationError as error:
            first = error.errors()[0]
            name = ".".join(map(str, (key, *first["loc"])))
            raise GpgpuError(f"{name}: {first['msg']} (set in {self._sources.get(name, 'the configuration')})") from None

    def tool(self, name: str) -> str:
        """The configured command of an external tool."""
        return str(self.get(f"tools.{name}.command"))

    @cached_property
    def build_root(self) -> Path:
        raw = self.get("paths.build.root")
        if not isinstance(raw, str) or not raw:
            raise GpgpuError("paths.build.root must be a non-empty string")
        root = (self.repo_root / Path(raw).expanduser()).resolve()
        if root == self.repo_root or root in self.repo_root.parents:
            raise GpgpuError("paths.build.root must not be the repository root or one of its ancestors")
        for name in _PROTECTED:
            protected = self.repo_root / name
            if root == protected or protected in root.parents or root in protected.parents:
                raise GpgpuError(f"paths.build.root overlaps protected repository directory: {protected}")
        return root

    def as_dict(self) -> dict[str, Any]:
        return self._values

    def keys(self) -> list[str]:
        return sorted(self._sources)

    def unknown_keys(self) -> list[str]:
        """Keys a local layer set that the default profile does not define."""
        def walk(values: dict[str, Any], known: Any, prefix: str) -> Iterator[str]:
            for key, value in values.items():
                if not isinstance(known, dict) or key not in known:
                    yield f"{prefix}{key}"
                elif isinstance(value, dict):
                    yield from walk(value, known[key], f"{prefix}{key}.")
        return list(walk(self._values, self._default, ""))
