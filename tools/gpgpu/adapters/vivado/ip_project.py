"""DesignProject for the IP: the project holds flat copies of the RTL, so sync is file by file.

What the IP Packager writes (component.xml) comes from tcl/package_ip.tcl and the RTL. It can be
detected but not pulled, because Vivado cannot export a packaged IP as a script that rebuilds it.
That kind of edit is made in package_ip.tcl, and Vivado's journal lists its Tcl commands.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

from gpgpu.api import Action, SyncRefused, SyncReport, SyncState, classify, command_line


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""


def tree_hash(directory: Path) -> dict[str, str]:
    """Every file under a published IP repository, except its own stamp."""
    result = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise RuntimeError(f"Package contains symbolic link: {path}")
        if path.is_file() and path.name != ".gpgpu-package.json":
            result[path.relative_to(directory).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


class IpProject:
    name = "ip"
    create_task = "vivado:ip:create"
    # The build packages the committed RTL, so project edits would be ignored or discarded.
    # Committed edits are fine: the graph recreates the project from them.
    blocked_by = frozenset({SyncState.PROJECT_AHEAD, SyncState.DIVERGED})

    def __init__(self, *, vivado: str, repo: Path, directory: Path, xpr: Path, ip_repo: Path, inputs: Sequence[Path], recreate: Action) -> None:
        self._vivado, self._repo, self._dir, self._xpr, self._ip_repo = vivado, repo, directory, xpr, ip_repo
        self._inputs = {path.name: path for path in inputs}  # names are unique: everything is staged flat
        self._recreate = recreate
        self._baseline = directory / ".gpgpu/sync/staged.json"

    def _record_baseline(self) -> None:
        self._baseline.parent.mkdir(parents=True, exist_ok=True)
        self._baseline.write_text(json.dumps({name: _sha(path) for name, path in self._inputs.items()}))

    def recording_baseline(self, action: Action) -> Action:
        """Wrap the task that builds this project: a new project matches the committed RTL."""
        def run() -> None:
            action()
            self._record_baseline()
        return run

    def _edited_files(self, baseline: dict[str, str]) -> list[str]:
        return [name for name in baseline if _sha(self._dir / "src" / name) != baseline[name]]

    def _edited_metadata(self) -> list[str]:
        stamp = self._ip_repo / ".gpgpu-package.json"
        if not stamp.is_file():
            return []
        recorded, current = json.loads(stamp.read_text()).get("files", {}), tree_hash(self._ip_repo)
        return [f"ip_repo/{name}" for name in sorted(recorded.keys() | current.keys()) if recorded.get(name) != current.get(name)]

    def _forget_metadata_edits(self) -> None:
        """After --force: stop reporting them, and remove the package so the next build makes it anew."""
        stamp = self._ip_repo / ".gpgpu-package.json"
        if self._edited_metadata():
            (self._ip_repo / "component.xml").unlink(missing_ok=True)
            stamp.write_text(json.dumps({**json.loads(stamp.read_text()), "files": tree_hash(self._ip_repo)}, sort_keys=True, indent=2) + "\n")

    def status(self) -> SyncReport:
        if not self._xpr.is_file():
            return SyncReport(self.name, SyncState.NOT_CREATED)
        if not self._baseline.is_file():
            return SyncReport(self.name, SyncState.UNTRACKED)
        baseline = json.loads(self._baseline.read_text())
        project = (*(f"src/{name}" for name in self._edited_files(baseline)), *self._edited_metadata())
        source = tuple(str(path.relative_to(self._repo)) for name, path in self._inputs.items() if _sha(path) != baseline.get(name))
        return SyncReport(self.name, classify(bool(project), bool(source)), project, source)

    def pull(self, *, force: bool = False) -> SyncReport:
        """Project -> committed RTL: copy back the staged files edited in the GUI."""
        current = self.status()
        if current.state is SyncState.NOT_CREATED:
            raise SyncRefused(f"{self.name} has no project yet", f"Run `{command_line(self.create_task)}`")
        if current.state in (SyncState.IN_SYNC, SyncState.UNTRACKED):
            return current
        if current.state is SyncState.SOURCE_AHEAD:
            raise SyncRefused(f"{self.name} is source ahead: nothing to pull", f"Run `{command_line(self.create_task)}`")
        if current.state is SyncState.DIVERGED and not force:
            raise SyncRefused(f"{self.name} is diverged: pull would overwrite {', '.join(current.source_changes)}",
                              "Use `pull --force` to discard those edits, or `push` to keep them")
        metadata = self._edited_metadata()
        if metadata and not force:
            script = (Path(__file__).parent / "tcl/package_ip.tcl").relative_to(self._repo)
            raise SyncRefused(f"{', '.join(metadata)} cannot be pulled: Vivado cannot export a packaged IP as a script",
                              f"Copy your edit's Tcl commands from {self._dir / 'vivado.jou'} into {script}. "
                              "`pull --force` pulls the RTL and drops this edit")
        baseline = json.loads(self._baseline.read_text())
        for name in self._edited_files(baseline):
            shutil.copy2(self._dir / "src" / name, self._inputs[name])
        self._record_baseline()
        self._forget_metadata_edits()
        return self.status()

    def push(self, *, force: bool = False) -> SyncReport:
        """Committed RTL -> project: recreate it. The previous project is kept as a snapshot."""
        current = self.status()
        if current.state is SyncState.IN_SYNC:
            return current
        if current.state in (SyncState.PROJECT_AHEAD, SyncState.DIVERGED) and not force:
            raise SyncRefused(f"{self.name} is {current.state.value}: push would discard {len(current.project_changes)} project change(s)",
                              "Use `push --force` to discard them, or `pull` to keep them")
        self._recreate()
        self._record_baseline()
        self._forget_metadata_edits()
        return self.status()

    def open(self) -> None:
        subprocess.Popen([self._vivado, str(self._xpr)], cwd=self._dir, start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
