"""Persistent per-task logs and metadata for ``gpgpu run`` executions."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from threading import Lock, Thread
from typing import IO, Any

from doit.reporter import ConsoleReporter
from doit.task import Task

from .run_monitor import BuildDashboard


class _FdTee:
    """Tee both process file descriptors to their terminal and one binary log."""

    def __init__(self, log_path: Path, *, mirror: bool = True) -> None:
        self.log_path = log_path
        self.mirror = mirror
        self._log: IO[bytes] | None = None
        self._saved_fds: dict[int, int] = {}
        self._threads: list[Thread] = []
        self._lock = Lock()
        self._saved_streams: dict[str, object] = {}

    def start(self) -> None:
        self._flush_streams()
        try:
            self._log = self.log_path.open("wb")
            for fd in (1, 2):
                saved_fd = os.dup(fd)
                self._saved_fds[fd] = saved_fd
                read_fd, write_fd = os.pipe()
                try:
                    os.dup2(write_fd, fd)
                    thread = Thread(target=self._copy, args=(read_fd, saved_fd), daemon=True)
                    thread.start()
                    self._threads.append(thread)
                except BaseException:
                    os.close(read_fd)
                    raise
                finally:
                    os.close(write_fd)
            self._wrap_python_stream("stdout", 1)
            self._wrap_python_stream("stderr", 2)
        except BaseException:
            self.stop()
            raise

    def stop(self) -> None:
        self._flush_streams()
        for name, stream in self._saved_streams.items():
            setattr(sys, name, stream)
        for fd, saved_fd in self._saved_fds.items():
            os.dup2(saved_fd, fd)
        for thread in self._threads:
            thread.join()
        for saved_fd in self._saved_fds.values():
            os.close(saved_fd)
        if self._log is not None:
            self._log.close()
            self._log = None
        self._saved_fds.clear()
        self._saved_streams.clear()
        self._threads.clear()

    def _wrap_python_stream(self, name: str, fd: int) -> None:
        stream = getattr(sys, name)
        try:
            if stream.fileno() == fd:
                return
        except (AttributeError, OSError):
            pass
        self._saved_streams[name] = stream
        setattr(sys, name, _TextTee(stream, self))

    def write_text(self, content: str) -> None:
        encoded = content.encode("utf-8", errors="replace")
        with self._lock:
            if self._log is not None:
                self._log.write(encoded)
                self._log.flush()

    def _copy(self, read_fd: int, terminal_fd: int) -> None:
        try:
            while chunk := os.read(read_fd, 65536):
                with self._lock:
                    if self._log is not None:
                        self._log.write(chunk)
                        self._log.flush()
                if self.mirror:
                    try:
                        _write_all(terminal_fd, chunk)
                    except OSError:
                        pass  # Broken terminal must not stop draining task output.
        finally:
            os.close(read_fd)

    @staticmethod
    def _flush_streams() -> None:
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.flush()
            except (AttributeError, ValueError, OSError):
                pass


class _TextTee:
    """Mirror Python-level writes when a capture framework replaced sys streams."""

    def __init__(self, original: object, capture: _FdTee) -> None:
        self.original = original
        self.capture = capture

    def write(self, content: str) -> int:
        written = self.original.write(content) if self.capture.mirror else len(content)  # type: ignore[attr-defined]
        self.capture.write_text(content)
        return len(content) if written is None else written

    def flush(self) -> None:
        self.original.flush()  # type: ignore[attr-defined]

    def isatty(self) -> bool:
        return bool(getattr(self.original, "isatty", lambda: False)())

    @property
    def encoding(self) -> str:
        return getattr(self.original, "encoding", "utf-8")


def _write_all(fd: int, content: bytes) -> None:
    offset = 0
    while offset < len(content):
        offset += os.write(fd, content[offset:])


def _slug(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")
    return normalized or "task"


def _git_metadata(repo_root: Path) -> tuple[str | None, bool]:
    try:
        commit = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--short", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "-C", str(repo_root), "status", "--porcelain"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None, False
    return commit, dirty


def _failure_exit_code(failure: object) -> int:
    text = getattr(failure, "get_msg", lambda: str(failure))()
    patterns = (r"returned\s+(\d+)", r"exit status\s+(\d+)")
    for pattern in patterns:
        if match := re.search(pattern, text):
            return int(match.group(1))
    return 1


class RunLogReporter(ConsoleReporter):
    """A pydoit reporter that records each stage while preserving live output."""

    desc = "stream task output and save per-run logs"

    def __init__(self, outstream: object, options: dict[str, object], *, repo_root: Path, requested_task: str, monitor: bool = False) -> None:
        super().__init__(outstream, options)
        self.repo_root = repo_root
        self.requested_task = requested_task
        self.started = datetime.now().astimezone()
        self.run_id, self.run_dir = self._create_run_dir()
        commit, dirty = _git_metadata(repo_root)
        self.metadata: dict[str, Any] = {
            "run_id": self.run_id,
            "requested_task": requested_task,
            "started_at": self.started.isoformat(timespec="seconds"),
            "finished_at": None,
            "exit_code": None,
            "git_commit": commit,
            "git_dirty": dirty,
            "tasks": [],
        }
        self._task_records: dict[str, dict[str, Any]] = {}
        self._started_at: dict[str, float] = {}
        self._capture: _FdTee | None = None
        self._active_task: str | None = None
        self._selected_task: Task | None = None
        # Records pydoit has reached (executed, skipped or failed) lead the
        # plan in the order it reached them; the rest keep dependency order.
        self._reached = 0
        self._monitor_requested = monitor
        self._dashboard: BuildDashboard | None = None
        self._write_metadata()

    def write(self, text: str) -> None:
        if not self._dashboard_active():
            super().write(text)

    def _dashboard_active(self) -> bool:
        return self._dashboard is not None and self._dashboard.active

    def _dashboard_failed(self) -> None:
        capture = self._capture
        if capture is not None:
            capture.mirror = True

    def _create_run_dir(self) -> tuple[str, Path]:
        runs_dir = self.repo_root / "logs/runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        base = f"{self.started.strftime('%Y-%m-%dT%H%M%S')}_{_slug(self.requested_task)}"
        run_id = base
        suffix = 2
        while (runs_dir / run_id).exists():
            run_id = f"{base}-{suffix}"
            suffix += 1
        run_dir = runs_dir / run_id
        run_dir.mkdir()
        return run_id, run_dir

    def initialize(self, tasks: dict[str, Task], selected_tasks: list[str]) -> None:
        planned: list[Task] = []
        visited: set[str] = set()

        def visit(task_name: str) -> None:
            if task_name in visited or task_name not in tasks:
                return
            visited.add(task_name)
            task = tasks[task_name]
            # Setup tasks execute after regular prerequisites and before the
            # requested action; include them in the same ordered stage plan.
            for dependency in (*task.task_dep, *task.setup_tasks):
                visit(dependency)
            if task.actions:
                planned.append(task)

        for task_name in selected_tasks:
            visit(task_name)

        namespace = self.requested_task.rpartition(":")[0]
        prefix = f"{namespace}:" if namespace else ""
        for task in planned:
            label = task.name.removeprefix(prefix) if task.name.startswith(prefix) else task.name
            record: dict[str, Any] = {"task": task.name, "status": "not_run"}
            self.metadata["tasks"].append(record)
            # The log name is numbered when pydoit reaches the task (_reach).
            self._task_records[task.name] = {"record": record, "label": label, "log_name": None}
        self._write_metadata()

        if self._monitor_requested:
            self._dashboard = BuildDashboard(self.run_dir, self._dashboard_failed)
            self._dashboard.start()

    def _reach(self, task_info: dict[str, Any]) -> str:
        """Place a record at pydoit's actual execution position; name its log.

        The dependency-order plan cannot predict pydoit's scheduling: a
        prerequisite without dependencies of its own runs before a deep chain
        declared ahead of it. Positions and log numbers follow execution.
        """
        if task_info["log_name"] is None:
            tasks = self.metadata["tasks"]
            record = task_info["record"]
            index = next(i for i, item in enumerate(tasks) if item is record)
            tasks.insert(self._reached, tasks.pop(index))
            task_info["log_name"] = f"{self._reached:02d}_{_slug(task_info['label'])}.log"
            self._reached += 1
        return task_info["log_name"]

    def get_status(self, task: Task) -> None:
        # pydoit calls this BEFORE dependency/uptodate callbacks, not just
        # before actions. Keep selection separate from the active output tee.
        self._selected_task = task
        super().get_status(task)

    def execute_task(self, task: Task) -> None:
        # Setup tasks can cause a task to be selected twice; pydoit omits
        # get_status on that second selection.
        self._selected_task = task
        task_info = self._task_records.get(task.name)
        if task_info is None:
            super().execute_task(task)
            return
        record = task_info["record"]
        log_name = self._reach(task_info)
        record["status"] = "running"
        record["log"] = log_name
        record["started_at"] = datetime.now().astimezone().isoformat(timespec="microseconds")
        self._started_at[task.name] = time.perf_counter()
        self._active_task = task.name
        self._capture = _FdTee(self.run_dir / log_name, mirror=not self._dashboard_active())
        self._capture.start()
        # Refresh may fail between evaluating mirror and assigning the capture.
        # Once assigned, the failure callback can safely restore mirroring too.
        if not self._dashboard_active():
            self._capture.mirror = True
        print(f".  {task.title()}", flush=True)
        self._write_metadata()

    def add_success(self, task: Task) -> None:
        self._finish_task(task, "success")
        self._selected_task = None
        super().add_success(task)

    def add_failure(self, task: Task, fail: object) -> None:
        task_info = self._failure_task_info(task)
        if task_info is not None:
            task_info["record"]["exit_code"] = _failure_exit_code(fail)
            message = getattr(fail, "get_msg", lambda: str(fail))()
            task_info["record"]["error"] = message
            # Emit the runner exception before closing the task's live tee.
            # Vendor output may indicate success even when artifact validation fails.
            if self._active_task == task.name:
                print(f"ERROR: {message}", flush=True)
            else:
                self.write(f"ERROR: {message}\n")
            if self._active_task != task.name:
                task_info["record"]["log"] = task_info["log_name"]
                with (self.run_dir / task_info["log_name"]).open("a", encoding="utf-8") as log:
                    log.write(f"ERROR: {message}\n")
        self._finish_task(task, "failed")
        self._selected_task = None
        super().add_failure(task, fail)  # type: ignore[arg-type]

    def runtime_error(self, msg: str) -> None:
        # ConsoleReporter's final summary is hidden while Live is active. Keep
        # runner errors in the same JSON source as the rest of the dashboard.
        super().runtime_error(msg)
        exception = sys.exc_info()[1]
        detail = "".join(traceback.format_exception(exception)) if exception is not None else msg
        self._record_runtime_error(detail, exit_code=2)

    def _failure_task_info(self, task: Task) -> dict[str, Any]:
        if task.name not in self._task_records:
            # Successful dependency-only aggregates remain absent from the
            # stage plan; a failed aggregate must still be attributable.
            record = {"task": task.name, "status": "not_run"}
            # Reached now: it goes right after everything pydoit already reached.
            self.metadata["tasks"].insert(self._reached, record)
            self._reached += 1
            self._task_records[task.name] = {
                "record": record, "label": task.name,
                "log_name": f"diagnostic-{_slug(task.name)}.log",
            }
        task_info = self._task_records[task.name]
        self._reach(task_info)
        return task_info

    def _record_runtime_error(self, message: str, *, exit_code: int) -> None:
        task = self._selected_task
        heading = f"ERROR: task '{task.name}'" if task is not None else "ERROR: runner"
        diagnostic = f"{heading}\n{message.rstrip()}\n"
        with (self.run_dir / "diagnostics.log").open("a", encoding="utf-8") as log:
            log.write(diagnostic)
        self.metadata["error"] = "\n".join(filter(None, (self.metadata.get("error"), message.rstrip())))
        self.metadata["diagnostics_log"] = "diagnostics.log"
        if task is not None:
            info = self._failure_task_info(task)
            record = info["record"]
            # Never transfer an error to an already completed prerequisite.
            if record["status"] in ("not_run", "running"):
                record.update(error=message.rstrip(), exit_code=exit_code, log=info["log_name"])
                if self._active_task == task.name and self._capture is not None:
                    self._capture.write_text(diagnostic)
                else:
                    with (self.run_dir / info["log_name"]).open("a", encoding="utf-8") as log:
                        log.write(diagnostic)
                self._finish_task(task, "failed")
        self._selected_task = None
        self._write_metadata()

    def complete_run(self) -> None:
        # Runner.run_all calls finish() in its finally block. Unhandled
        # callback exceptions bypass both add_failure and runtime_error, but
        # their traceback is still available here before DoitMain returns 3.
        exception = sys.exc_info()[1]
        if isinstance(exception, Exception):
            trace = exception.__traceback__
            while trace is not None:
                runner = trace.tb_frame.f_locals.get("self")
                if trace.tb_frame.f_code.co_name == "run_all" and getattr(runner, "reporter", None) is self:
                    self._record_runtime_error("".join(traceback.format_exception(exception)), exit_code=3)
                    break
                trace = trace.tb_next
        # DoitMain owns console tracebacks for uncaught exceptions; normal
        # runtime_error messages use ConsoleReporter (or dashboard JSON).
        super().complete_run()

    def skip_uptodate(self, task: Task) -> None:
        self._selected_task = None
        task_info = self._task_records.get(task.name)
        if task_info is not None:
            self._reach(task_info)
            task_info["record"]["status"] = "up_to_date"
            self._write_metadata()
        super().skip_uptodate(task)

    def skip_ignore(self, task: Task) -> None:
        self._selected_task = None
        super().skip_ignore(task)

    def _finish_task(self, task: Task, status: str) -> None:
        task_info = self._task_records.get(task.name)
        if task_info is None:
            return
        started = self._started_at.get(task.name)
        duration = round(time.perf_counter() - started, 3) if started is not None else None
        if self._capture is not None and self._active_task == task.name:
            self._capture.stop()
            self._capture = None
            self._active_task = None
        record = task_info["record"]
        record["status"] = status
        if duration is not None:
            record["duration_s"] = duration
        self._write_metadata()

    def finalize(self, exit_code: int) -> None:
        try:
            self._finalize(exit_code)
        finally:
            if self._dashboard is not None:
                self._dashboard.stop()

    def _finalize(self, exit_code: int) -> None:
        finished = time.perf_counter()
        if self._capture is not None:
            self._capture.stop()
            self._capture = None
        for record in self.metadata["tasks"]:
            if record["status"] == "running":
                record["status"] = "interrupted" if exit_code == 130 else "failed"
                record["duration_s"] = round(finished - self._started_at[record["task"]], 3)
        self._active_task = None
        failed_exit_codes = [
            record.get("exit_code", 1)
            for record in self.metadata["tasks"]
            if record["status"] == "failed"
        ]
        recorded_exit_code = failed_exit_codes[0] if failed_exit_codes else exit_code
        self.metadata["finished_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        self.metadata["exit_code"] = recorded_exit_code
        self._write_metadata()
        logs_dir = self.repo_root / "logs"
        self._replace_symlink(logs_dir / "latest")
        if exit_code:
            self._replace_symlink(logs_dir / "last-failed")

    def _replace_symlink(self, path: Path) -> None:
        if path.is_symlink() or path.exists():
            path.unlink()
        path.symlink_to(Path("runs") / self.run_id, target_is_directory=True)

    def _write_metadata(self) -> None:
        temporary = self.run_dir / "run.json.tmp"
        temporary.write_text(json.dumps(self.metadata, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.run_dir / "run.json")
