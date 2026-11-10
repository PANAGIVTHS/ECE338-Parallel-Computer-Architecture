"""Starting external programs, checking that they are there, and locking the build tree."""
from __future__ import annotations

import fcntl
import os
import shutil
import subprocess
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from gpgpu.api import CheckResult, GpgpuError

from .config import Config

_REQUIRED_DIRECTORIES = ("config", "hardware/rtl", "hardware/constraints", "software/host", "software/programs",
                         "tests/hardware/rtl")


def run(command: Sequence[str], cwd: Path | None = None, creates: Path | None = None) -> None:
    """Run one program, failing the task if it fails. *creates* is made first."""
    if creates is not None:
        creates.mkdir(parents=True, exist_ok=True)
    subprocess.run(list(command), cwd=cwd, check=True)


class Machine:
    """Environment: the configured tools, the repository's directories and the build tree's locks."""

    def __init__(self, config: Config) -> None:
        self._config = config

    @contextmanager
    def exclusive(self, categories: Iterable[str], command: str) -> Iterator[None]:
        """One command per category of a build tree. The kernel frees the locks however this process ends."""
        directory = self._config.build_root / ".locks"
        directory.mkdir(parents=True, exist_ok=True)
        locks = []
        try:
            for category in sorted(categories):
                locks.append((directory / category).open("a+"))
                try:
                    fcntl.flock(locks[-1], fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    locks[-1].seek(0)
                    raise GpgpuError(f"{locks[-1].read() or 'Another command'} is using the {category} tasks of this build tree",
                                     "Wait for it, or use another paths.build.root") from None
            for lock in locks:
                lock.truncate(0)
                lock.write(f"`{command}` (process {os.getpid()})")
                lock.flush()
            yield
        finally:
            for lock in locks:
                lock.close()

    def checks(self) -> list[CheckResult]:
        config = self._config
        checks = [CheckResult("configuration", True, f"profile {config.profile}")]
        for name, tool in config.get("tools").items():
            command = str(tool["command"])
            found = shutil.which(str(config.repo_root / Path(command).expanduser()) if "/" in command else command)
            checks.append(CheckResult(name, found is not None, found or f"{command} not found", bool(tool.get("required"))))
        for directory in _REQUIRED_DIRECTORIES:
            checks.append(CheckResult(directory, (config.repo_root / directory).is_dir(), "repository directory"))
        checks.append(CheckResult("paths.build.root", True, str(config.build_root)))
        return checks
