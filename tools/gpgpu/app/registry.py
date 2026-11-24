"""Collects what plugins declare. A plugin that fails only costs its own commands."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from types import ModuleType

from gpgpu.api import Backends, DesignProject, GpgpuError, PluginFailure, Task


@dataclass(slots=True)
class Catalog:
    tasks: dict[str, Task] = field(default_factory=dict)
    projects: dict[str, DesignProject] = field(default_factory=dict)
    unavailable: dict[str, str] = field(default_factory=dict)  # task -> why it did not load
    failures: list[PluginFailure] = field(default_factory=list)


class Registry:
    def __init__(self, plugins: Mapping[str, ModuleType], failures: Iterable[PluginFailure] = ()) -> None:
        self._plugins = plugins
        self._failures = tuple(failures)

    def categories(self) -> dict[str, str]:
        """Category -> one-line help. A plugin's file name is its category."""
        return {name: (plugin.__doc__ or name).strip().splitlines()[0] for name, plugin in self._plugins.items()}

    def collect(self, backend: Backends) -> Catalog:
        catalog = Catalog(failures=list(self._failures))
        for name, plugin in self._plugins.items():
            try:
                tasks = plugin.tasks(backend)
                projects = plugin.projects(backend) if hasattr(plugin, "projects") else []
                foreign = [task.name for task in tasks if task.category != name]
                if foreign:
                    raise ValueError(f"{name}.py may only declare {name}:* tasks, not {foreign}")
            except GpgpuError as error:
                catalog.failures.append(PluginFailure(name, error.message))
            except Exception as error:
                catalog.failures.append(PluginFailure(name, f"{type(error).__name__}: {error}"))
            else:
                catalog.tasks.update((task.name, task) for task in tasks)
                catalog.projects.update((project.name, project) for project in projects)
        _prune(catalog)
        return catalog


def _prune(catalog: Catalog) -> None:
    """Drop tasks whose prerequisites did not load, so the rest of the graph stays valid."""
    changed = True
    while changed:
        changed = False
        for task in list(catalog.tasks.values()):
            missing = [name for name in (*task.needs, *task.setup, *task.requires) if name not in catalog.tasks]
            if missing:
                catalog.unavailable[task.name] = catalog.unavailable.get(missing[0], f"it needs {missing[0]}, which did not load")
                del catalog.tasks[task.name]
                changed = True
