"""TaskLoader2 implementation and programmatic pydoit runner."""

from __future__ import annotations

import importlib.util
import os
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any, cast

from doit.cmd_base import TaskLoader2
from doit.doit_cmd import DoitMain
from doit.task import Task, dict_to_task

from .project_paths import ProjectPaths
from .run_logging import RunLogReporter

if TYPE_CHECKING:
    from config import ResolvedConfig


_TASK_MODULES = (
    "tools/software/programs.py",
    "tools/software/host_platform.py",
    "tools/tests/rtl.py",
    "tools/hardware/vivado/tasks.py",
    "tools/hardware/vitis/tasks.py",
    "tools/hardware/fpga/tasks.py",
)


def _load_module(path: Path) -> ModuleType:
    module_name = f"gpgpu_tasks_{path.stem}"
    specification = importlib.util.spec_from_file_location(module_name, path)
    if specification is None or specification.loader is None:
        raise ImportError(f"Could not load task module: {path}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


class GPGPUTaskLoader(TaskLoader2):
    """Load GPGPU tasks using one immutable CLI-resolved configuration."""

    def __init__(self, resolved_config: ResolvedConfig) -> None:
        super().__init__()
        self.resolved_config = resolved_config

    def load_doit_config(self) -> dict[str, object]:
        """Place pydoit's dependency database in the configured build tree."""

        build_path = ProjectPaths.from_config(self.resolved_config).build_root
        build_path.mkdir(parents=True, exist_ok=True)
        # Use an explicit single-file backend so `.doit.db` has identical
        # semantics on platforms whose dbm implementations add suffixes.
        return {
            "dep_file": str(build_path / ".doit.db"),
            "backend": "sqlite3",
        }

    def load_tasks(self, cmd: object, pos_args: list[str]) -> list[Task]:
        """Load task dictionaries from repository modules and convert them."""

        task_dicts: list[dict[str, Any]] = []
        for relative_path in _TASK_MODULES:
            path = self.resolved_config.repo_root / relative_path
            module = _load_module(path)
            create_tasks = getattr(module, "create_tasks", None)
            if not callable(create_tasks):
                raise TypeError(f"Task module does not define create_tasks(config): {path}")
            factory = cast(Callable[[Any], list[dict[str, Any]]], create_tasks)
            task_dicts.extend(factory(self.resolved_config))
        return [dict_to_task(task) for task in task_dicts]


def create_task_loader(resolved_config: ResolvedConfig) -> GPGPUTaskLoader:
    """Create a loader bound to one resolved CLI configuration."""

    return GPGPUTaskLoader(resolved_config)


def run(resolved_config: ResolvedConfig, arguments: Sequence[str] = ()) -> int:
    """Execute pydoit programmatically using the resolved CLI configuration."""

    loader = create_task_loader(resolved_config)
    result = DoitMain(loader, config_filenames=()).run(list(arguments))
    return 0 if result is None else result


def run_logged_task(resolved_config: ResolvedConfig, task: str, *, monitor: bool | None = None) -> int:
    """Run one task dependency graph with live, persistent per-stage logs."""

    loader = create_task_loader(resolved_config)
    reporter = RunLogReporter(
        sys.stdout,
        {"failure_verbosity": 0},
        repo_root=resolved_config.repo_root,
        requested_task=task,
        monitor=(bool(sys.stdout.isatty()) and os.isatty(1) and not os.environ.get("CI")) if monitor is None else monitor,
    )
    status = 3
    try:
        result = DoitMain(
            loader,
            config_filenames=(),
            extra_config={"run": {"reporter": reporter}},
        ).run(["run", "--verbosity=2", task])
        status = 0 if result is None else result
        return status
    except KeyboardInterrupt:
        status = 130
        raise
    finally:
        reporter.finalize(status)
