"""The application API: every use case, for the CLI, scripts and tests alike."""
from __future__ import annotations

import difflib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import cached_property

from gpgpu.api import (Backends, CheckResult, DesignProject, Environment, GpgpuError, Settings, SyncRefused,
                       SyncReport, SyncState, Task, TaskEngine, command_line)

from .registry import Catalog, Registry


class Workspace:
    def __init__(self, settings: Settings, registry: Registry, backend: Backends, engine: TaskEngine,
                 environment: Environment) -> None:
        self.settings = settings
        self._registry = registry
        self._backend = backend
        self._engine = engine
        self._environment = environment

    @cached_property
    def _catalog(self) -> Catalog:
        return self._registry.collect(self._backend)

    # Discovery
    def tasks(self, category: str) -> list[Task]:
        """The category's commands in the order its plugin declares them, without internal stages."""
        self._require_loaded(category)
        return [task for task in self._catalog.tasks.values() if task.category == category and not task.hidden]

    def projects(self) -> list[str]:
        return sorted(self._catalog.projects)

    # Execution
    def run(self, target: str, *, monitor: bool = False, warn: Callable[[str], object] = print) -> int:
        """Run a task and its needs, and only those. Returns the exit code."""
        if target not in self._catalog.tasks:
            raise self._missing(target)
        tasks = self._closure(target)
        required = [self._catalog.tasks[name] for name in dict.fromkeys(name for task in tasks for name in task.requires)]
        with self._environment.exclusive({task.category for task in (*tasks, *required)}, command_line(target)):
            self._guard(tasks)
            self._check_required(target, required, warn)
            return self._engine.run(tasks, target, monitor=monitor)

    # Design sync
    def status(self, project: str) -> SyncReport:
        return self._project(project).status()

    def pull(self, project: str, *, force: bool = False) -> SyncReport:
        with self._holding(project, "pull") as design:
            return design.pull(force=force)

    def push(self, project: str, *, force: bool = False) -> SyncReport:
        with self._holding(project, "push") as design:
            return design.push(force=force)

    def open(self, project: str) -> None:
        design = self._project(project)
        if design.status().state is SyncState.NOT_CREATED and self.run(design.create_task):
            raise GpgpuError(f"{design.create_task} failed, so {project} was not opened")
        design.open()

    # Environment
    def doctor(self) -> list[CheckResult]:
        return [*self._environment.checks(),
                *(CheckResult(f"plugin {failure.plugin}", False, failure.error) for failure in self._catalog.failures)]

    def validate(self) -> tuple[list[str], list[str]]:
        """(errors, warnings) in the configuration: what the plugins rejected, and unknown keys."""
        return ([failure.error for failure in self._catalog.failures],
                [f"Unknown option: {key}" for key in self.settings.unknown_keys()])

    # Rules
    def _project(self, name: str) -> DesignProject:
        if name not in self._catalog.projects:
            raise GpgpuError(f"No project named {name!r}", f"Known projects: {', '.join(self.projects()) or 'none'}")
        return self._catalog.projects[name]

    @contextmanager
    def _holding(self, project: str, verb: str) -> Iterator[DesignProject]:
        design = self._project(project)
        with self._environment.exclusive({self._catalog.tasks[design.create_task].category}, f"gpgpu project {verb} {project}"):
            yield design

    def _closure(self, target: str) -> list[Task]:
        """A task and everything that runs for it."""
        found: dict[str, Task] = {}
        pending = [target]
        while pending:
            name = pending.pop()
            if name not in found:
                found[name] = self._catalog.tasks[name]
                pending += (*found[name].needs, *found[name].setup)
        return list(found.values())

    def _check_required(self, target: str, required: list[Task], warn: Callable[[str], object]) -> None:
        """A command never starts another category's builds. Missing results stop it; stale ones warn."""
        absent = {task.name: [path.name for path in task.step.outputs if not path.exists()] for task in required}
        absent = {name: files for name, files in absent.items() if files}
        if absent:
            raise GpgpuError(f"{command_line(target)} cannot start without {', '.join(file for files in absent.values() for file in files)}",
                             "Run " + " and ".join(f"`{command_line(name)}`" for name in absent))
        for task in required:
            reasons = self._engine.stale(self._closure(task.name))
            if reasons:
                warn(f"`{command_line(task.name)}` is out of date ({', '.join(reasons[:3])}): using its existing results")

    def _guard(self, tasks: list[Task]) -> None:
        """A build must not silently ignore or discard edits to a design it depends on."""
        names = {task.name for task in tasks}
        for project in self._catalog.projects.values():
            if project.create_task in names:
                report = project.status()
                if report.state in project.blocked_by:
                    edits = (*report.project_changes, *report.source_changes)
                    raise SyncRefused(f"{project.name} is {report.state.value}: this build would ignore "
                                      f"{', '.join(edits[:3])}",
                                      f"Run `gpgpu project pull {project.name}` to keep the GUI's version, or `push` to keep the committed one")

    def _require_loaded(self, category: str) -> None:
        for failure in self._catalog.failures:
            if failure.plugin == category:
                raise GpgpuError(f"The {category} commands did not load: {failure.error}")

    def _missing(self, target: str) -> GpgpuError:
        catalog = self._catalog
        if target in catalog.unavailable:
            return GpgpuError(f"{command_line(target)} is unavailable: {catalog.unavailable[target]}",
                              "; ".join(f"{failure.plugin}: {failure.error}" for failure in catalog.failures) or None)
        category = target.partition(":")[0]
        self._require_loaded(category)
        close = difflib.get_close_matches(target, catalog.tasks, n=3)
        return GpgpuError(f"No command `{command_line(target)}`",
                          f"Did you mean: {', '.join(map(command_line, close))}" if close
                          else f"Run `gpgpu {category} --help` to list them")
