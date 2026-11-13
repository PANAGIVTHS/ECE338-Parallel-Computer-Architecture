"""The live build monitor. Renders only from the run's run.json and its stage logs."""
from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from threading import Event, Thread
from typing import Any

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

_MARKERS = {"success": "✓", "running": "●", "failed": "✗", "interrupted": "✗", "up_to_date": "✓"}
_STYLES = {"success": "green", "running": "bold cyan", "failed": "bold red", "interrupted": "bold yellow", "up_to_date": "yellow"}
_HEADLINE = {"FAILED": "bold red", "INTERRUPTED": "bold yellow", "SUCCESS": "bold green"}


class BuildDashboard:
    """Owns the terminal and a 4 Hz refresh thread. A display failure never fails the build."""

    def __init__(self, run_dir: Path, on_failure: Callable[[], None]) -> None:
        self.renderer = RunMonitor(run_dir)
        self.on_failure = on_failure
        self.active = False
        self._stop = Event()
        self._thread: Thread | None = None
        self._terminal: Any = None
        self._live: Live | None = None

    def start(self) -> None:
        try:
            # Keep a descriptor of its own: stage capture takes over stdout and stderr.
            self._terminal = os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)
            self._live = Live(console=Console(file=self._terminal, force_terminal=True), auto_refresh=False,
                              redirect_stdout=False, redirect_stderr=False, vertical_overflow="crop")
            self._live.start()
            self.active = True
            self._refresh()
            self._thread = Thread(target=self._run, name="gpgpu-build-monitor", daemon=True)
            self._thread.start()
        except Exception:
            self.active = False
            self.on_failure()
            self._close()

    def _refresh(self) -> None:
        assert self._live is not None
        size = self._live.console.size
        self._live.update(self.renderer.render(width=size.width, height=max(1, size.height - 1)), refresh=True)

    def _run(self) -> None:
        try:
            while not self._stop.wait(0.25):
                self._refresh()
        except Exception:
            self.active = False
            self.on_failure()
        finally:
            self._close()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
            self._thread = None
        else:
            self._close()
        self.active = False

    def _close(self) -> None:
        try:
            if self._live is not None:
                self._refresh()  # the final run.json, after capture has drained
                self._live.stop()
        except Exception:
            self.on_failure()
        finally:
            self._live = None
            if self._terminal is not None:
                self._terminal.close()
                self._terminal = None


class RunMonitor:
    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        self.snapshot: dict[str, Any] = {}

    def _read_snapshot(self) -> dict[str, Any]:
        try:
            self.snapshot = json.loads((self.run_dir / "run.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass  # keep the last good state
        return self.snapshot

    def _tail(self, tasks: list[dict[str, Any]], lines: int) -> list[str]:
        logged = [task for task in tasks if task.get("log")]
        task = next((task for task in logged if task.get("status") == "running"), logged[-1] if logged else None)
        if task is None or lines <= 0:
            return []
        try:
            with (self.run_dir / task["log"]).open("rb") as log:
                log.seek(max(0, log.seek(0, os.SEEK_END) - 65536))
                content = log.read().decode("utf-8", errors="replace")
        except OSError:
            return []
        return [Text.from_ansi(line).plain for line in content.splitlines()[-lines:]]  # strips escape codes

    def render(self, *, width: int = 80, height: int = 24) -> Panel | Text:
        snapshot = self._read_snapshot()
        tasks = snapshot.get("tasks", [])
        done = sum(task.get("status") in ("success", "up_to_date") for task in tasks)
        code = snapshot.get("exit_code")
        status = "RUNNING" if code is None else {0: "SUCCESS", 130: "INTERRUPTED"}.get(code, "FAILED")
        lines = [f"{snapshot.get('requested_task', 'Waiting for run.json')}  {status}  {done}/{len(tasks)} stages"]
        styles = [_HEADLINE.get(status, "bold cyan")]
        if height < 3 or width < 5:
            return Text(lines[0][:max(1, width)], no_wrap=True)
        capacity = height - 2
        if capacity >= 2 and width >= 12:
            fraction = done / len(tasks) if tasks else float(code == 0)
            bar = max(1, min(28, width - 12))
            lines.append(f"{'█' * int(fraction * bar)}{'░' * (bar - int(fraction * bar))} {fraction:.0%}")
            styles.append("green")
        # Keep room for a log tail, and keep the active stage visible in a long plan.
        reserve = min(4, max(0, capacity - len(lines) - 1)) if any(task.get("log") for task in tasks) else 0
        budget = min(len(tasks), max(0, capacity - len(lines) - reserve))
        focus = next((i for i, task in enumerate(tasks) if task.get("status") in ("running", "failed", "interrupted")), None)
        start = min(focus, max(0, focus - budget + 2), len(tasks) - budget) if focus is not None and focus >= budget else 0
        for task in tasks[start:start + budget]:
            state = task.get("status", "not_run")
            detail = "UP TO DATE" if state == "up_to_date" else state.upper().replace("NOT_RUN", "PENDING")
            duration = task.get("duration_s")
            if state == "running" and task.get("started_at"):
                duration = max(0, (datetime.now().astimezone() - datetime.fromisoformat(task["started_at"])).total_seconds())
            lines.append(f"{_MARKERS.get(state, '○')} {task['task']}  {detail}" + (f" {duration:.1f}s" if duration is not None else ""))
            styles.append(_STYLES.get(state, "dim"))
        tail = self._tail(tasks, capacity - len(lines) - 1)
        if tail:
            lines += ["── Live log ──", *tail]
            styles += ["dim cyan", *[""] * len(tail)]
        body = Text(no_wrap=True, overflow="crop")
        for index, line in enumerate(lines[:capacity]):
            part = Text(line, style=styles[index])
            part.truncate(max(1, width - 4), overflow="ellipsis")
            body.append("\n" if index else "")
            body.append(part)
        return Panel(body, title=Text("GPGPU Build Monitor", style="bold cyan"), border_style="cyan",
                     width=width, height=min(height, len(lines) + 2))
