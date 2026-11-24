"""DesignProject for the block design: a generated script in git, the project in the build tree.

The script is a write_bd_tcl export, so it stays reviewable and rebuilds the design exactly.
Settings the configuration owns (cores, aperture, clock) are applied over it on every build.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from gpgpu.api import Action, GpgpuError, SyncRefused, SyncReport, SyncState, classify, command_line

_TCL = Path(__file__).parent / "tcl"
_IGNORED = ("ip_revision",)  # changes on every repackage; not a design edit
# What a GUI save without Validate Design drops. The next validation restores it.
_UNVALIDATED = re.compile(r"(design_info|port: \S+): < (validated|CLK_DOMAIN|FREQ_TOLERANCE_HZ|INSERT_VIP|PHASE)=")


def canonicalize(text: str) -> str:
    """Sort the pins of each net, so an IP upgrade reordering them is not a diff."""
    lines, out, index = text.splitlines(), [], 0
    while index < len(lines):
        line = lines[index]
        if re.match(r"\s*connect_bd_net\b", line) and line.rstrip().endswith("\\"):
            statement = [line]
            while statement[-1].rstrip().endswith("\\"):
                index += 1
                statement.append(lines[index])
            joined = " ".join(part.rstrip(" \\").strip() for part in statement)
            head = joined[: joined.index("[")].rstrip()
            pins = sorted(re.findall(r"\[get_bd_\w+ [^\]]+\]", joined))
            indent = line[: len(line) - len(line.lstrip())]
            out += [f"{indent}{head} {pins[0]} \\", *(f"{indent}{pin} \\" for pin in pins[1:-1]), f"{indent}{pins[-1]}"]
        else:
            out.append(line)
        index += 1
    return "\n".join(out) + "\n"


class SystemProject:
    name = "system"
    create_task = "vivado:system:create"
    # The project is what gets built, so its own GUI edits build fine. Script edits would be ignored.
    blocked_by = frozenset({SyncState.SOURCE_AHEAD, SyncState.DIVERGED})

    def __init__(self, *, vivado: str, repo: Path, directory: Path, xpr: Path, bd: Path, ip_repo: Path, part: str, script: Path,
                 top: str, cores: int, base: str, size: str, fclk: str) -> None:
        self._vivado_command, self._repo, self._dir, self._xpr, self._bd = vivado, repo, directory, xpr, bd
        self._ip_repo, self._part, self._script, self._top = ip_repo, part, script, top
        self._cores, self._base, self._size, self._fclk = cores, base, size, fclk
        self._sync = directory / ".gpgpu/sync"
        self._baseline, self._hash = self._sync / "baseline.bd", self._sync / "script.sha256"

    def _vivado(self, script: str, *args: object, cwd: Path) -> str:
        result = subprocess.run([self._vivado_command, "-mode", "batch", "-nojournal", "-nolog", "-source", str(_TCL / script),
                                 "-tclargs", *map(str, args)], cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        if result.returncode:
            # From the first error: the last one only says "failed due to earlier errors".
            found = re.search(r"^ERROR.*?(?=^\s+while executing|\Z)", result.stdout, re.M | re.S)
            raise GpgpuError(f"Vivado {script} failed:\n{found[0].strip() if found else result.stdout[-400:]}")
        return result.stdout

    def _functional_diff(self, before: Path, after: Path) -> tuple[str, ...]:
        diffbd = Path(shutil.which(self._vivado_command) or self._vivado_command).resolve().with_name("diffbd")
        if not diffbd.is_file():
            raise GpgpuError(f"{diffbd} not found: it ships beside vivado", "Set tools.vivado.command to the installed vivado")
        # Read the report: diffbd's exit status is the difference count modulo 256.
        report = subprocess.run([str(diffbd), str(before), str(after)], capture_output=True, text=True).stdout
        component, changes = "", []
        for line in report.splitlines():
            if not line.startswith(" ") and line.strip():
                component = line.split(",")[0].replace("component:", "").strip()
            elif re.match(r" [<>] ", line) and not any(word in line for word in _IGNORED):
                changes.append(f"{component}: {line.strip()}")
        return tuple(change for change in changes if not _UNVALIDATED.match(change))

    def _sha(self) -> str:
        return hashlib.sha256(self._script.read_bytes()).hexdigest() if self._script.is_file() else ""

    def _record_baseline(self) -> None:
        self._sync.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self._bd, self._baseline)
        self._hash.write_text(self._sha())

    def _config_drift(self) -> tuple[str, ...]:
        """Values the next build will overwrite: only the configuration owns these."""
        parts = json.loads(self._bd.read_text())["design"]["components"]
        drift = []
        for label, cell, parameter, expected in (("FCLK0 MHz", "processing_system7_0", "PCW_FPGA0_PERIPHERAL_FREQMHZ", self._fclk),
                                                 ("Cores", "gpgpu_axi_0", "SP_PER_SM", self._cores)):
            value = parts.get(cell, {}).get("parameters", {}).get(parameter, {}).get("value")
            if value is not None and float(value) != float(expected):
                drift.append(f"{label} is {value} in the project; config says {expected}")
        return tuple(drift)

    def status(self) -> SyncReport:
        if not self._bd.is_file():
            return SyncReport(self.name, SyncState.NOT_CREATED)
        if not self._baseline.is_file() or not self._hash.is_file():
            return SyncReport(self.name, SyncState.UNTRACKED, config_drift=self._config_drift())
        project = self._functional_diff(self._baseline, self._bd)
        source = self._hash.read_text() != self._sha()
        return SyncReport(self.name, classify(bool(project), source), project,
                          (str(self._script.relative_to(self._repo)),) if source else (), self._config_drift())

    def keeping_baseline(self, action: Action) -> Action:
        """Wrap the task that builds this project.

        From a new or in-sync project, whatever it changes comes from the script and the
        configuration, so the baseline follows. Only edits outside the graph stay visible.
        """
        def run() -> None:
            state = self.status().state
            action()
            if state in (SyncState.NOT_CREATED, SyncState.IN_SYNC):
                self._record_baseline()
        return run

    def pull(self, *, force: bool = False) -> SyncReport:
        """Project -> script, only after the new script is proven to rebuild this exact design."""
        current = self.status()
        if current.state is SyncState.NOT_CREATED:
            raise SyncRefused(f"{self.name} has no project yet", f"Run `{command_line(self.create_task)}`")
        if current.state is SyncState.IN_SYNC:
            return current
        if current.state in (SyncState.SOURCE_AHEAD, SyncState.DIVERGED) and not force:
            raise SyncRefused(f"{self.name} is {current.state.value}: pull would overwrite {', '.join(current.source_changes)}",
                              "Use `pull --force` to discard those edits, or `push` to keep them")
        with tempfile.TemporaryDirectory(prefix="gpgpu-pull-") as temporary:
            work = Path(temporary)
            raw = work / "raw.tcl"
            self._vivado("sync_export.tcl", self._xpr, self._bd.stem, raw, cwd=work)
            candidate = work / self._script.name
            candidate.write_text(canonicalize(raw.read_text()))
            # Rebuilt without the configuration overlay: the export alone must reproduce the design.
            output = self._vivado("sync_rebuild.tcl", candidate, self._bd.stem, self._ip_repo, self._part, work / "rebuilt", cwd=work)
            rebuilt = Path(re.findall(r"^GPGPU_REBUILT (.+)$", output, re.M)[-1])
            differences = self._functional_diff(self._bd, rebuilt)
            if differences:
                raise SyncRefused(f"The exported script does not reproduce {self.name}; "
                                  f"{self._script.name} was left unchanged: {differences[:3]}")
            self._script.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(candidate, self._script)
        self._record_baseline()
        return self.status()

    def push(self, *, force: bool = False) -> SyncReport:
        """Script -> project. The replaced design is kept as a snapshot."""
        current = self.status()
        if current.state is SyncState.NOT_CREATED:
            raise SyncRefused(f"{self.name} has no project yet", f"Run `{command_line(self.create_task)}`")
        if current.state is SyncState.IN_SYNC:
            return current
        if not self._script.is_file():
            raise SyncRefused(f"{self._script} does not exist", "Run `pull` first")
        if current.state in (SyncState.PROJECT_AHEAD, SyncState.DIVERGED) and not force:
            raise SyncRefused(f"{self.name} is {current.state.value}: push would discard {len(current.project_changes)} project change(s)",
                              "Use `push --force` to discard them, or `pull` to keep them")
        snapshots = self._dir / ".gpgpu/bd-snapshots"
        snapshots.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self._bd, snapshots / f"{self._bd.stem}-{uuid.uuid4().hex}.bd")
        self._vivado("sync_push.tcl", self._xpr, self._script, _TCL / "configure_block_design.tcl", self._bd.stem, self._top,
                     self._cores, self._base, self._size, self._fclk, cwd=self._dir)
        self._record_baseline()
        return self.status()

    def open(self) -> None:
        subprocess.Popen([self._vivado_command, str(self._xpr)], cwd=self._dir, start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
