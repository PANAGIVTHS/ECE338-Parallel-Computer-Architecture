"""TaskEngine on pydoit. The only module that knows pydoit's task format and .doit.db."""
from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from doit.cmd_base import TaskLoader2
from doit.dependency import Dependency, SqliteDB
from doit.doit_cmd import DoitMain
from doit.task import dict_to_task
from doit.tools import config_changed

from gpgpu.api import Action, Predicate, StateProbe, Task

from .config import Config
from .run_log import RunLogReporter


class _PredicateCheck:
    def __init__(self, predicate: Predicate) -> None:
        self.predicate = predicate

    def __call__(self, task: Any, values: Any) -> bool:
        # A check that raises means stale: the action then reports the problem, with its log.
        try:
            return self.predicate()
        except Exception:
            return False


def _stored(value: object) -> Any:
    """The form a value takes after a trip through the database, which stores JSON."""
    return json.loads(json.dumps(value))


class _StateCheck:
    def __init__(self, probe: StateProbe) -> None:
        self.probe = probe

    def configure_task(self, task: Any) -> None:
        task.value_savers.append(lambda: {self.probe.key: _stored(self.probe.state())})

    def __call__(self, task: Any, values: Any) -> bool:
        # No saved value means stale, even when state() returns None.
        return self.probe.key in values and bool(values[self.probe.key] == _stored(self.probe.state()))


def _action(action: Action) -> Any:
    """pydoit reads an action's return value and its parameter names; hide both."""
    def run() -> None:
        action()
    return run


def to_doit(task: Task) -> dict[str, Any]:
    step = task.step
    uptodate: list[Any] = [False] if step.always_run else []
    if step.fingerprint is not None:
        uptodate.append(config_changed(dict(step.fingerprint)))
    uptodate += [_StateCheck(check) if isinstance(check, StateProbe) else _PredicateCheck(check) for check in step.checks]
    return {"name": task.name, "doc": task.doc, "actions": [_action(step.action)] if step.action else None,
            "task_dep": list(task.needs), "setup": list(task.setup), "file_dep": [str(path) for path in step.inputs],
            "targets": [str(path) for path in step.outputs], "uptodate": uptodate}


def _in_words(reasons: dict[str, Any]) -> list[str]:
    """Why pydoit says a task is stale: its changed and missing files, or else its settings."""
    return [*(f"{Path(path).name} changed" for path in reasons.get("changed_file_dep", ())),
            *(f"{Path(path).name} missing" for kind in ("missing_file_dep", "missing_target") for path in reasons.get(kind, ()))
            ] or ["settings changed"]


class _Loader(TaskLoader2):
    def __init__(self, config: Config, tasks: Sequence[Task]) -> None:
        super().__init__()
        self._config, self._tasks = config, tasks

    def load_doit_config(self) -> dict[str, object]:
        self._config.build_root.mkdir(parents=True, exist_ok=True)
        return {"dep_file": str(self._config.build_root / ".doit.db"), "backend": "sqlite3"}

    def load_tasks(self, cmd: object, pos_args: list[str]) -> list[Any]:
        # Only this run's tasks: pydoit silently runs the producer of any input it knows about.
        return [dict_to_task(to_doit(task)) for task in self._tasks]


class DoitEngine:
    def __init__(self, config: Config) -> None:
        self._config = config

    def stale(self, tasks: Sequence[Task]) -> list[str]:
        """Why these tasks would rerun. A step that always runs says nothing about its results."""
        built = {task.name: dict_to_task(to_doit(task)) for task in tasks}
        database = Dependency(SqliteDB, str(self._config.build_root / ".doit.db"))
        reasons: dict[str, None] = {}
        for task in reversed(tasks):  # what comes first in the flow is the likely cause
            if task.step.action and not task.step.always_run:
                status = database.get_status(built[task.name], built, get_log=True)
                if status.status != "up-to-date":
                    reasons.update(dict.fromkeys(_in_words(status.reasons)))
        database.close()
        return list(reasons)

    def run(self, tasks: Sequence[Task], target: str, *, monitor: bool) -> int:
        reporter = RunLogReporter(sys.stdout, {"failure_verbosity": 0}, repo_root=self._config.repo_root,
                                  requested_task=target, monitor=monitor)
        status = 3
        try:
            result = DoitMain(_Loader(self._config, tasks), config_filenames=(),
                              extra_config={"run": {"reporter": reporter}}).run(["run", "--verbosity=2", target])
            status = 0 if result is None else int(result)
            # pydoit: 1 task failed, 2 task raised, 3 bad invocation.
            return {0: 0, 1: 1, 2: 1}.get(status, 2)
        except KeyboardInterrupt:
            status = 130
            raise
        finally:
            reporter.finalize(status)
