from __future__ import annotations

import json
from pathlib import Path

from src import run_logged_task


class StubResolvedConfig:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root

    @property
    def build_root(self) -> Path:
        return self.repo_root / "build"


def make_task_repo(tmp_path: Path) -> StubResolvedConfig:
    programs = tmp_path / "tools/software/programs.py"
    programs.parent.mkdir(parents=True)
    programs.write_text(
        "import subprocess\n"
        "import sys\n"
        "\n"
        "def first():\n"
        "    print('python output from first', flush=True)\n"
        "    subprocess.run([sys.executable, '-c', \"print('child output from first', flush=True)\"], check=True)\n"
        "\n"
        "def second():\n"
        "    subprocess.run([sys.executable, '-c', \"import sys; print('child failure output', flush=True); sys.exit(7)\"], check=True)\n"
        "\n"
        "def success():\n"
        "    print('successful output', flush=True)\n"
        "\n"
        "def create_tasks(config):\n"
        "    return [\n"
        "        {'name': 'demo:first', 'actions': [first], 'uptodate': [False]},\n"
        "        {'name': 'demo:second', 'actions': [second], 'task_dep': ['demo:first'], 'uptodate': [False]},\n"
        "        {'name': 'demo:third', 'actions': [lambda: None], 'task_dep': ['demo:second'], 'uptodate': [False]},\n"
        "        {'name': 'demo:all', 'actions': None, 'task_dep': ['demo:third']},\n"
        "        {'name': 'success:stage', 'actions': [success], 'uptodate': [False]},\n"
        "        {'name': 'success:all', 'actions': None, 'task_dep': ['success:stage']},\n"
        "    ]\n",
        encoding="utf-8",
    )
    for relative_path in (
        "tools/software/host_platform.py",
        "tools/tests/rtl.py",
        "tools/hardware/vivado/tasks.py",
        "tools/hardware/vitis/tasks.py",
        "tools/hardware/fpga/tasks.py",
    ):
        module = tmp_path / relative_path
        module.parent.mkdir(parents=True, exist_ok=True)
        module.write_text("def create_tasks(config):\n    return []\n", encoding="utf-8")
    return StubResolvedConfig(tmp_path)


def test_failed_run_streams_and_records_each_task_in_dependency_order(
    tmp_path: Path, capfd
) -> None:
    config = make_task_repo(tmp_path)

    status = run_logged_task(config, "demo:all")  # type: ignore[arg-type]

    assert status == 2
    terminal_output = capfd.readouterr()
    combined_output = terminal_output.out + terminal_output.err
    assert "python output from first" in combined_output
    assert "child output from first" in combined_output
    assert "child failure output" in combined_output

    runs = list((tmp_path / "logs/runs").iterdir())
    assert len(runs) == 1
    run_dir = runs[0]
    assert run_dir.name.endswith("_demo-all")
    assert (tmp_path / "logs/latest").resolve() == run_dir
    assert (tmp_path / "logs/last-failed").resolve() == run_dir

    first_log = run_dir / "00_first.log"
    second_log = run_dir / "01_second.log"
    assert "python output from first" in first_log.read_text(encoding="utf-8")
    assert "child output from first" in first_log.read_text(encoding="utf-8")
    assert "child failure output" in second_log.read_text(encoding="utf-8")
    assert not (run_dir / "02_third.log").exists()

    metadata = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert metadata["run_id"] == run_dir.name
    assert metadata["requested_task"] == "demo:all"
    assert metadata["started_at"]
    assert metadata["finished_at"]
    assert metadata["exit_code"] == 7
    assert isinstance(metadata["git_dirty"], bool)
    assert metadata["tasks"][0] == {
        "task": "demo:first",
        "status": "success",
        "duration_s": metadata["tasks"][0]["duration_s"],
        "log": "00_first.log",
        "started_at": metadata["tasks"][0]["started_at"],
    }
    assert metadata["tasks"][0]["duration_s"] >= 0
    assert metadata["tasks"][1]["task"] == "demo:second"
    assert metadata["tasks"][1]["status"] == "failed"
    assert metadata["tasks"][1]["exit_code"] == 7
    assert metadata["tasks"][1]["duration_s"] >= 0
    assert metadata["tasks"][1]["log"] == "01_second.log"
    assert metadata["tasks"][2] == {"task": "demo:third", "status": "not_run"}


def test_successful_run_updates_latest_without_replacing_last_failed(tmp_path: Path) -> None:
    config = make_task_repo(tmp_path)
    assert run_logged_task(config, "demo:all") == 2  # type: ignore[arg-type]
    failed_run = (tmp_path / "logs/last-failed").resolve()

    assert run_logged_task(config, "success:all") == 0  # type: ignore[arg-type]

    successful_run = (tmp_path / "logs/latest").resolve()
    assert successful_run != failed_run
    assert (tmp_path / "logs/last-failed").resolve() == failed_run
    metadata = json.loads((successful_run / "run.json").read_text(encoding="utf-8"))
    assert metadata["exit_code"] == 0
    assert metadata["tasks"][0]["status"] == "success"
    assert metadata["tasks"][0]["log"] == "00_stage.log"
    assert "successful output" in (successful_run / "00_stage.log").read_text(
        encoding="utf-8"
    )


def test_python_validation_failure_is_visible_in_task_log_and_metadata(tmp_path: Path, capfd) -> None:
    config = make_task_repo(tmp_path)
    (tmp_path / "tools/software/programs.py").write_text(
        "def validate():\n"
        "    print('Platform Build Finished successfully.', flush=True)\n"
        "    raise FileNotFoundError('Vitis completed without producing required artifacts: missing.bit')\n"
        "def create_tasks(config):\n"
        "    return [{'name': 'validate:all', 'actions': [validate]}]\n",
        encoding="utf-8",
    )
    assert run_logged_task(config, "validate:all") == 2
    output = capfd.readouterr()
    message = "Vitis completed without producing required artifacts: missing.bit"
    assert message in output.out + output.err
    run_dir = (tmp_path / "logs/last-failed").resolve()
    metadata = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    task = metadata["tasks"][0]
    assert message in (run_dir / task["log"]).read_text(encoding="utf-8")
    assert message in task["error"]


def test_monitor_captures_python_and_child_without_dashboard_in_stage_logs(tmp_path, capfd):
    config = make_task_repo(tmp_path)
    assert run_logged_task(config, "demo:all", monitor=True) == 2
    run_dir = (tmp_path / "logs/latest").resolve()
    first = (run_dir / "00_first.log").read_text()
    assert "python output from first" in first
    assert "child output from first" in first
    assert "GPGPU Build Monitor" not in first
    assert "\x1b" not in first
    output = capfd.readouterr().out
    assert "GPGPU Build Monitor" in output


def test_auto_monitor_is_disabled_in_pipes_and_plain_override(tmp_path, capfd):
    config = make_task_repo(tmp_path)
    for option in [None, False]:
        assert run_logged_task(config, "success:all", monitor=option) == 0
        output = capfd.readouterr().out
        assert "successful output" in output
        assert "GPGPU Build Monitor" not in output


def test_interrupted_reporter_finishes_active_stage_and_releases_capture(tmp_path):
    import sys
    from datetime import datetime

    from doit.task import Task
    from src.run_logging import RunLogReporter

    original = (sys.stdout, sys.stderr)
    reporter = RunLogReporter(sys.stdout, {}, repo_root=tmp_path, requested_task="demo:all")
    active = Task("demo:active", [lambda: None])
    pending = Task("demo:pending", [lambda: None], task_dep=[active.name])
    reporter.initialize({active.name: active, pending.name: pending}, [pending.name])
    reporter.execute_task(active)
    reporter.finalize(130)
    snapshot = json.loads((reporter.run_dir / "run.json").read_text())
    assert snapshot["tasks"][0]["status"] == "interrupted"
    assert datetime.fromisoformat(snapshot["tasks"][0]["started_at"])
    assert snapshot["tasks"][0]["duration_s"] >= 0
    assert snapshot["tasks"][1]["status"] == "not_run"
    assert reporter._capture is None
    assert (sys.stdout, sys.stderr) == original


def test_dashboard_refresh_failure_restores_raw_output_and_cleans_up(tmp_path, capfd, monkeypatch):
    from src.run_monitor import RunMonitor

    config = make_task_repo(tmp_path)
    path = tmp_path / "tools/software/programs.py"
    path.write_text("import time\ndef stage():\n    time.sleep(0.4)\n    print('after dashboard failure', flush=True)\ndef create_tasks(config):\n    return [{'name': 'fixture', 'actions': [stage]}]\n")
    render = RunMonitor.render
    calls = 0

    def broken_refresh(self, **kwargs):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise RuntimeError('broken rendering')
        return render(self, **kwargs)

    monkeypatch.setattr(RunMonitor, 'render', broken_refresh)
    assert run_logged_task(config, 'fixture', monitor=True) == 0
    assert 'after dashboard failure' in capfd.readouterr().out
    import threading
    assert not any(t.name == 'gpgpu-build-monitor' for t in threading.enumerate())


def test_keyboard_interrupt_fixture_marks_json_and_releases_every_resource(tmp_path, capfd):
    import sys
    import threading

    import pytest

    config = make_task_repo(tmp_path)
    (tmp_path / 'tools/software/programs.py').write_text("def stage():\n    print('before interrupt', flush=True)\n    raise KeyboardInterrupt()\ndef create_tasks(config):\n    return [{'name': 'interrupt', 'actions': [stage]}, {'name': 'pending', 'actions': [lambda: None], 'task_dep': ['interrupt']}]\n")
    streams = sys.stdout, sys.stderr
    descriptors = len(list(Path('/proc/self/fd').iterdir()))
    threads = set(threading.enumerate())
    with pytest.raises(KeyboardInterrupt):
        run_logged_task(config, 'pending', monitor=True)
    run_dir = (tmp_path / 'logs/latest').resolve()
    metadata = json.loads((run_dir / 'run.json').read_text())
    assert metadata['exit_code'] == 130
    assert [t['status'] for t in metadata['tasks']] == ['interrupted', 'not_run']
    assert 'before interrupt' in (run_dir / metadata['tasks'][0]['log']).read_text()
    assert 'INTERRUPTED' in capfd.readouterr().out
    assert (sys.stdout, sys.stderr) == streams
    assert set(threading.enumerate()) == threads
    assert len(list(Path('/proc/self/fd').iterdir())) == descriptors


def test_unknown_task_preinit_failure_leaves_no_dashboard(tmp_path, capfd):
    config = make_task_repo(tmp_path)
    assert run_logged_task(config, 'unknown', monitor=True) == 3
    snapshot = json.loads((tmp_path / 'logs/latest/run.json').read_text())
    assert snapshot['exit_code'] == 3
    assert snapshot['tasks'] == []
    assert 'GPGPU Build Monitor' not in capfd.readouterr().out


def test_uptodate_stage_has_no_start_timestamp_or_log(tmp_path, capfd):
    config = make_task_repo(tmp_path)
    (tmp_path / 'tools/software/programs.py').write_text("def create_tasks(config):\n    return [{'name': 'cached', 'actions': [lambda: None], 'uptodate': [True]}]\n")
    assert run_logged_task(config, 'cached', monitor=True) == 0
    snapshot = json.loads((tmp_path / 'logs/latest/run.json').read_text())
    assert snapshot['tasks'] == [{'task': 'cached', 'status': 'up_to_date'}]
    assert 'UP TO DATE' in capfd.readouterr().out


def test_partial_fd_capture_setup_restores_streams_and_closes_descriptors(tmp_path, monkeypatch):
    import os
    import sys
    import threading

    import pytest
    from src.run_logging import _FdTee

    pipe = os.pipe
    calls = 0
    def failing_pipe():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError('fixture pipe failure')
        return pipe()

    streams = sys.stdout, sys.stderr
    descriptors = len(list(Path('/proc/self/fd').iterdir()))
    threads = set(threading.enumerate())
    monkeypatch.setattr(os, 'pipe', failing_pipe)
    capture = _FdTee(tmp_path / 'stage.log')
    try:
        with pytest.raises(OSError, match='fixture pipe failure'):
            capture.start()
        assert not capture._saved_fds
        assert capture._log is None
        assert (sys.stdout, sys.stderr) == streams
        assert set(threading.enumerate()) == threads
        assert len(list(Path('/proc/self/fd').iterdir())) == descriptors
    finally:
        capture.stop()


def test_real_pty_auto_monitor_and_ci_fallback_capture_both_streams(tmp_path):
    import errno
    import os
    import pty
    import select
    import subprocess
    import sys
    import time

    make_task_repo(tmp_path)
    (tmp_path / 'tools/software/programs.py').write_text(
        "import subprocess, sys, time\n"
        "def stage():\n"
        "    print('python stdout', flush=True)\n"
        "    print('python stderr', file=sys.stderr, flush=True)\n"
        "    subprocess.run([sys.executable, '-c', \"import sys; print('child stdout'); print('child stderr', file=sys.stderr)\"], check=True)\n"
        "    time.sleep(0.35)\n"
        "def create_tasks(config):\n"
        "    return [{'name': 'pty:fixture', 'actions': [stage], 'uptodate': [False]}]\n"
    )
    script = (
        "import sys\nfrom pathlib import Path\n"
        f"sys.path.insert(0, {str(Path(__file__).resolve().parent)!r})\n"
        "from test_run_logging import StubResolvedConfig\nfrom src import run_logged_task\n"
        f"sys.exit(run_logged_task(StubResolvedConfig(Path({str(tmp_path)!r})), 'pty:fixture'))\n"
    )
    for ci in [False, True]:
        master, slave = pty.openpty()
        env = dict(os.environ, TERM='xterm-256color', PYTHONPATH=str(Path(__file__).resolve().parents[1]))
        if ci:
            env['CI'] = '1'
        else:
            env.pop('CI', None)
        child = subprocess.Popen([sys.executable, '-c', script], stdout=slave, stderr=slave, env=env)
        os.close(slave)
        output = bytearray()
        deadline = time.monotonic() + 10
        try:
            while time.monotonic() < deadline:
                if select.select([master], [], [], 0.1)[0]:
                    try:
                        chunk = os.read(master, 65536)
                    except OSError as error:
                        if error.errno == errno.EIO:
                            break
                        raise
                    if not chunk:
                        break
                    output.extend(chunk)
            assert child.wait(timeout=2) == 0, output.decode(errors='replace')
        finally:
            os.close(master)
            if child.poll() is None:
                child.kill()
                child.wait()
        text = output.decode(errors='replace')
        assert ('GPGPU Build Monitor' in text) == (not ci)
        if not ci:
            assert 'SUCCESS' in text
        snapshot = json.loads((tmp_path / 'logs/latest/run.json').read_text())
        log = (tmp_path / 'logs/latest' / snapshot['tasks'][0]['log']).read_text()
        for expected in ['python stdout', 'python stderr', 'child stdout', 'child stderr']:
            assert expected in log
            assert expected in text
        assert 'GPGPU Build Monitor' not in log
        assert '\x1b' not in log


def test_dashboard_thread_start_failure_preserves_task_status_and_plain_output(tmp_path, monkeypatch, capfd):
    from threading import Thread

    config = make_task_repo(tmp_path)
    start = Thread.start
    def failed_start(self):
        if self.name == 'gpgpu-build-monitor':
            raise RuntimeError('fixture worker start failed')
        return start(self)
    monkeypatch.setattr(Thread, 'start', failed_start)
    assert run_logged_task(config, 'success:all', monitor=True) == 0
    assert 'successful output' in capfd.readouterr().out


def test_stage_duration_ends_at_action_completion_not_log_drain(tmp_path, monkeypatch):
    import sys

    from doit.task import Task
    from src import run_logging

    clock = [10.0]
    monkeypatch.setattr(run_logging.time, 'perf_counter', lambda: clock[0])
    reporter = run_logging.RunLogReporter(sys.stdout, {}, repo_root=tmp_path, requested_task='fixture')
    task = Task('fixture', [lambda: None])
    reporter.initialize({task.name: task}, [task.name])
    reporter.execute_task(task)
    stop = reporter._capture.stop
    def draining():
        stop()
        clock[0] = 20.0
    reporter._capture.stop = draining
    clock[0] = 12.0
    try:
        reporter.add_success(task)
        snapshot = json.loads((reporter.run_dir / 'run.json').read_text())
        assert snapshot['tasks'][0]['duration_s'] == 2.0
    finally:
        reporter.finalize(0)


def test_dashboard_failure_during_capture_setup_cannot_leave_mirroring_disabled(tmp_path, capfd, monkeypatch):
    import sys

    from doit.task import Task
    from src import run_logging

    reporter = run_logging.RunLogReporter(sys.stdout, {}, repo_root=tmp_path, requested_task='fixture', monitor=True)
    task = Task('fixture', [lambda: None])
    reporter.initialize({task.name: task}, [task.name])
    init = run_logging._FdTee.__init__
    def failing_dashboard(self, *args, **kwargs):
        init(self, *args, **kwargs)
        reporter._dashboard.active = False
        reporter._dashboard_failed()  # Capture has not been assigned to reporter yet.
    monkeypatch.setattr(run_logging._FdTee, '__init__', failing_dashboard)
    try:
        reporter.execute_task(task)
        assert reporter._capture.mirror is True
    finally:
        reporter.finalize(130)
