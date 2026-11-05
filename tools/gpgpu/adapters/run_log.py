"""Per-run logs: logs/runs/<run>/run.json plus one log per stage, written as pydoit reports."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from threading import Lock, Thread
from typing import IO, Any

from doit.reporter import ConsoleReporter
from doit.task import Task

from .run_monitor import BuildDashboard


class _Capture:
    """Tee stdout and stderr, including child processes, into one log and the terminal."""

    def __init__(self, path: Path, *, mirror: bool) -> None:
        self.path, self.mirror = path, mirror
        self._log: IO[bytes] | None = None
        self._saved: dict[int, int] = {}
        self._threads: list[Thread] = []
        self._lock = Lock()

    def start(self) -> None:
        sys.stdout.flush()
        sys.stderr.flush()
        self._log = self.path.open("wb")
        for fd in (1, 2):
            self._saved[fd] = os.dup(fd)
            read_fd, write_fd = os.pipe()
            os.dup2(write_fd, fd)
            os.close(write_fd)
            thread = Thread(target=self._copy, args=(read_fd, self._saved[fd]), daemon=True)
            thread.start()
            self._threads.append(thread)

    def stop(self) -> None:
        sys.stdout.flush()
        sys.stderr.flush()
        for fd, saved in self._saved.items():
            os.dup2(saved, fd)
        for thread in self._threads:
            thread.join()
        for saved in self._saved.values():
            os.close(saved)
        if self._log is not None:
            self._log.close()

    def _copy(self, read_fd: int, terminal: int) -> None:
        while chunk := os.read(read_fd, 65536):
            with self._lock:
                assert self._log is not None
                self._log.write(chunk)
                self._log.flush()
            if self.mirror:
                try:
                    while chunk:
                        chunk = chunk[os.write(terminal, chunk):]
                except OSError:
                    pass  # a broken terminal must not stop draining task output
        os.close(read_fd)


def _slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._") or "task"


def _git(repo_root: Path, *arguments: str) -> str | None:
    try:
        return subprocess.run(["git", "-C", str(repo_root), *arguments], check=True, capture_output=True, text=True).stdout
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None


def _exit_code(message: str) -> int:
    match = re.search(r"(?:returned|exit status)\s+(\d+)", message)
    return int(match[1]) if match else 1


class RunLogReporter(ConsoleReporter):
    """Records each stage in run.json and its own log, keeping output live on the terminal."""

    desc = "stream task output and save per-run logs"

    def __init__(self, outstream: Any, options: dict[str, Any], *, repo_root: Path, requested_task: str, monitor: bool) -> None:
        super().__init__(outstream, options)
        self.repo_root = repo_root
        self._monitor = monitor
        started = datetime.now().astimezone()
        self.run_id, self.run_dir = self._create_run_dir(started, requested_task)
        self.metadata: dict[str, Any] = {
            "run_id": self.run_id, "requested_task": requested_task,
            "started_at": started.isoformat(timespec="seconds"), "finished_at": None, "exit_code": None,
            "git_commit": (_git(repo_root, "rev-parse", "--short", "HEAD") or "").strip() or None,
            "git_dirty": bool(_git(repo_root, "status", "--porcelain")), "tasks": []}
        self._records: dict[str, dict[str, Any]] = {}  # stage -> its entry in run.json
        self._logs: dict[str, str] = {}                # stage -> its log file name
        self._started: dict[str, float] = {}
        self._capture: _Capture | None = None
        self._active: str | None = None
        self._dashboard: BuildDashboard | None = None
        self._save()

    def _create_run_dir(self, started: datetime, task: str) -> tuple[str, Path]:
        runs = self.repo_root / "logs/runs"
        runs.mkdir(parents=True, exist_ok=True)
        base = run_id = f"{started.strftime('%Y-%m-%dT%H%M%S')}_{_slug(task)}"
        suffix = 2
        while (runs / run_id).exists():
            run_id, suffix = f"{base}-{suffix}", suffix + 1
        (runs / run_id).mkdir()
        return run_id, runs / run_id

    def _save(self) -> None:
        temporary = self.run_dir / "run.json.tmp"
        temporary.write_text(json.dumps(self.metadata, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.run_dir / "run.json")

    def _dashboard_active(self) -> bool:
        return self._dashboard is not None and self._dashboard.active

    def _dashboard_failed(self) -> None:
        if self._capture is not None:
            self._capture.mirror = True

    def write(self, text: str) -> None:
        if not self._dashboard_active():
            super().write(text)

    def initialize(self, tasks: dict[str, Task], selected_tasks: list[str]) -> None:
        # Plan the stages in run order; setup tasks run after needs, before the action.
        planned: list[Task] = []
        visited: set[str] = set()

        def visit(name: str) -> None:
            if name not in visited and name in tasks:
                visited.add(name)
                for dependency in (*tasks[name].task_dep, *tasks[name].setup_tasks):
                    visit(dependency)
                if tasks[name].actions:
                    planned.append(tasks[name])

        for name in selected_tasks:
            visit(name)
        for index, task in enumerate(planned):
            record = {"task": task.name, "status": "not_run"}
            self.metadata["tasks"].append(record)
            self._records[task.name] = record
            self._logs[task.name] = f"{index:02d}_{_slug(task.name)}.log"
        self._save()
        if self._monitor:
            self._dashboard = BuildDashboard(self.run_dir, self._dashboard_failed)
            self._dashboard.start()

    def execute_task(self, task: Task) -> None:
        record = self._records.get(task.name)
        if record is None:
            super().execute_task(task)
            return
        record.update(status="running", log=self._logs[task.name],
                      started_at=datetime.now().astimezone().isoformat(timespec="microseconds"))
        self._started[task.name] = time.perf_counter()
        self._active = task.name
        self._capture = _Capture(self.run_dir / self._logs[task.name], mirror=not self._dashboard_active())
        self._capture.start()
        if not self._dashboard_active():  # the dashboard may have failed since the line above
            self._capture.mirror = True
        print(f".  {task.title()}", flush=True)
        self._save()

    def add_success(self, task: Task) -> None:
        self._finish(task, "success")
        super().add_success(task)

    def add_failure(self, task: Task, fail: Any) -> None:
        message = fail.get_msg()
        if task.name == self._active:
            print(f"ERROR: {message}", flush=True)  # into the stage's log, before the capture closes
        else:
            self.write(f"ERROR: {message}\n")
            if task.name in self._records:  # failed before it started: a missing input
                self._records[task.name]["log"] = self._logs[task.name]
                (self.run_dir / self._logs[task.name]).write_text(f"ERROR: {message}\n", encoding="utf-8")
        if task.name in self._records:
            self._records[task.name].update(exit_code=_exit_code(message), error=message)
        self._finish(task, "failed")
        super().add_failure(task, fail)

    def skip_uptodate(self, task: Task) -> None:
        if task.name in self._records:
            self._records[task.name]["status"] = "up_to_date"
            self._save()
        super().skip_uptodate(task)

    def _finish(self, task: Task, status: str) -> None:
        record = self._records.get(task.name)
        if record is None:
            return
        if task.name == self._active and self._capture is not None:
            self._capture.stop()
            self._capture, self._active = None, None
        record["status"] = status
        if task.name in self._started:
            record["duration_s"] = round(time.perf_counter() - self._started[task.name], 3)
        self._save()

    def finalize(self, exit_code: int) -> None:
        """Called once by the engine, whatever happened, even on interruption."""
        try:
            if self._capture is not None:
                self._capture.stop()
                self._capture = None
            for record in self.metadata["tasks"]:
                if record["status"] == "running":
                    record["status"] = "interrupted" if exit_code == 130 else "failed"
                    record["duration_s"] = round(time.perf_counter() - self._started[record["task"]], 3)
            failed = [record.get("exit_code", 1) for record in self.metadata["tasks"] if record["status"] == "failed"]
            self.metadata.update(finished_at=datetime.now().astimezone().isoformat(timespec="seconds"),
                                 exit_code=failed[0] if failed else exit_code)
            self._save()
            self._link("latest")
            if exit_code:
                self._link("last-failed")
        finally:
            if self._dashboard is not None:
                self._dashboard.stop()

    def _link(self, name: str) -> None:
        link = self.repo_root / "logs" / name
        link.unlink(missing_ok=True)
        link.symlink_to(Path("runs") / self.run_id, target_is_directory=True)
