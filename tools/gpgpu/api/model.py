"""The vocabulary every layer shares. Knows no tool, engine or configuration."""
from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol, runtime_checkable


class GpgpuError(Exception):
    """An expected failure: the CLI prints the message and hint, without a traceback."""

    exit_code = 2

    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.message, self.hint = message, hint


class SyncRefused(GpgpuError):
    """Going ahead would lose or ignore someone's edits."""

    exit_code = 3


Action = Callable[[], object]
Predicate = Callable[[], bool]


@runtime_checkable
class StateProbe(Protocol):
    """Fresh while state() equals the value saved after the last success. Returns JSON types."""

    key: str

    def state(self) -> object: ...


FreshnessCheck = Predicate | StateProbe


@dataclass(frozen=True, slots=True)
class Step:
    """How a task runs and when it can be skipped. Adapters build these; plugins pass them on.

    A step with no inputs, fingerprint or checks always runs.
    """

    action: Action | None = None
    inputs: Sequence[Path] = ()                      # a content change makes it stale
    outputs: Sequence[Path] = ()                     # a missing output makes it stale
    fingerprint: Mapping[str, object] | None = None  # JSON settings; a change makes it stale
    checks: Sequence[FreshnessCheck] = ()            # extra freshness rules
    always_run: bool = False                         # never skipped, even with inputs

    def __post_init__(self) -> None:
        if self.fingerprint is not None:
            json.dumps(dict(self.fingerprint))       # a TypeError here is an adapter bug


@dataclass(frozen=True, slots=True)
class Task:
    """One command and its place in the graph. Plugins declare these."""

    name: str                       # "category:command" runs as `gpgpu category command`
    doc: str
    step: Step = Step()             # the default only groups its needs
    needs: tuple[str, ...] = ()     # run first, if stale
    setup: tuple[str, ...] = ()     # run after needs, only if this task will run
    requires: tuple[str, ...] = ()  # never run from here: missing outputs stop the command, stale ones warn

    @property
    def category(self) -> str:
        return self.name.partition(":")[0]

    @property
    def command(self) -> str:
        return self.name.partition(":")[2]

    @property
    def hidden(self) -> bool:
        """Internal stages are named with a leading underscore and left out of help."""
        return self.name.rpartition(":")[2].startswith("_")


def command_line(task: str) -> str:
    """How a user runs a task: "category:command" -> "gpgpu category command"."""
    return "gpgpu " + task.replace(":", " ", 1)


class SyncState(Enum):
    NOT_CREATED = "not created"
    UNTRACKED = "untracked"
    IN_SYNC = "in sync"
    PROJECT_AHEAD = "project ahead"
    SOURCE_AHEAD = "source ahead"
    DIVERGED = "diverged"


def classify(project_changed: bool, source_changed: bool) -> SyncState:
    if project_changed:
        return SyncState.DIVERGED if source_changed else SyncState.PROJECT_AHEAD
    return SyncState.SOURCE_AHEAD if source_changed else SyncState.IN_SYNC


@dataclass(frozen=True, slots=True)
class SyncReport:
    project: str
    state: SyncState
    project_changes: tuple[str, ...] = ()  # edited in the GUI since the last sync
    source_changes: tuple[str, ...] = ()   # committed files changed since the last sync
    config_drift: tuple[str, ...] = ()     # project values the configuration will overwrite


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    ok: bool
    detail: str = ""
    required: bool = True


@dataclass(frozen=True, slots=True)
class PluginFailure:
    plugin: str
    error: str
