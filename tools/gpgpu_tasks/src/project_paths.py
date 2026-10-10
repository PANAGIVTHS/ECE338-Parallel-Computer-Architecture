"""Canonical repository layout and paths derived from one configured build root."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class PathConfig(Protocol):
    """Minimal resolved-configuration contract needed for path derivation."""

    repo_root: Path

    @property
    def build_root(self) -> Path: ...


@dataclass(frozen=True, slots=True)
class ProjectPaths:
    """Fixed checkout paths and deterministic generated-output paths."""

    repo_root: Path
    build_root: Path

    @classmethod
    def from_config(cls, config: PathConfig) -> ProjectPaths:
        return cls(
            repo_root=config.repo_root.resolve(),
            build_root=config.build_root.resolve(),
        )

    @property
    def config(self) -> Path:
        return self.repo_root / "config"

    @property
    def hardware(self) -> Path:
        return self.repo_root / "hardware"

    @property
    def hardware_rtl(self) -> Path:
        return self.hardware / "rtl"
    
    @property
    def hardware_rtl_gpgpu(self) -> Path:
        return self.hardware / "rtl/gpgpu"

    @property
    def hardware_constraints(self) -> Path:
        return self.hardware / "constraints"

    @property
    def software(self) -> Path:
        return self.repo_root / "software"

    @property
    def software_host(self) -> Path:
        return self.software / "host"

    @property
    def software_programs(self) -> Path:
        return self.software / "programs"

    @property
    def tests(self) -> Path:
        return self.repo_root / "tests"

    @property
    def rtl_tests(self) -> Path:
        return self.tests / "hardware/rtl"

    @property
    def demo(self) -> Path:
        return self.repo_root / "demo"

    @property
    def hardware_build(self) -> Path:
        return self.build_root / "hardware"

    @property
    def vivado(self) -> Path:
        return self.hardware_build / "vivado"

    @property
    def hardware_reports(self) -> Path:
        return self.hardware_build / "reports"

    @property
    def bitstream(self) -> Path:
        return self.hardware_build / "bitstream"

    @property
    def platform(self) -> Path:
        return self.hardware_build / "platform"

    @property
    def software_build(self) -> Path:
        return self.build_root / "software"

    @property
    def vitis(self) -> Path:
        return self.software_build / "vitis"

    @property
    def program_builds(self) -> Path:
        return self.software_build / "programs"

    @property
    def test_build(self) -> Path:
        return self.build_root / "tests"

    @property
    def rtl_test_build(self) -> Path:
        return self.test_build / "rtl"

    def required_repository_paths(self) -> dict[str, Path]:
        """Return checkout paths whose absence indicates a broken repository."""

        return {
            "repository.config": self.config,
            "repository.hardware.rtl": self.hardware_rtl,
            "repository.hardware.constraints": self.hardware_constraints,
            "repository.software.host": self.software_host,
            "repository.software.programs": self.software_programs,
            "repository.tests.hardware.rtl": self.rtl_tests,
            "repository.demo": self.demo,
        }
