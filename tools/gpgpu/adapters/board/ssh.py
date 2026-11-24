"""Board on SSH: SCP uploads, and the shell helpers installed on the board's machine.

Commands are nested with shlex.join and run as argv, never through a local shell, so the
settings below only accept names and paths that are safe in a remote shell.
"""
from __future__ import annotations

import json
import re
import shlex
import subprocess
from functools import partial
from pathlib import Path, PurePosixPath
from typing import Annotated

from pydantic import AfterValidator, PositiveInt, StringConstraints

from gpgpu.api import Step

from ..config import Config, Section
from ..design import bitstream_path, program_names, program_output, vitis_workspace
from ..tools import run

_NAME = r"[A-Za-z0-9_][A-Za-z0-9_.-]*"


def _no_traversal(path: str) -> str:
    if any(part in (".", "..") for part in path.split("/")):
        raise ValueError("must not contain . or .. components")
    return path


SafeName = Annotated[str, StringConstraints(pattern=f"^{_NAME}$")]
Executable = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_./][A-Za-z0-9_./-]*$")]
Destination = Annotated[str, StringConstraints(pattern=r"^(?:[A-Za-z0-9_.][A-Za-z0-9_.-]*@)?[A-Za-z0-9_.][A-Za-z0-9_.-]*$")]
RemotePath = Annotated[str, StringConstraints(pattern=r"^/[A-Za-z0-9_./-]*$"), AfterValidator(_no_traversal)]


class _Agent(Section):
    device: SafeName
    directory: RemotePath | None  # where the board's agent sees the uploads; None: the upload directory


class _Uart(Section):
    port: RemotePath
    baud: PositiveInt
    sudo: bool
    python: Executable


class _Upload(Section):
    destination: Destination
    directory: RemotePath


class _Fpga(Section):
    part: str
    agent: _Agent
    uart: _Uart
    upload: _Upload


class _Commands(Section):
    ssh: Executable
    scp: Executable


class SshBoard:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._s = config.section("hardware.fpga", _Fpga)
        commands = _Commands(ssh=config.tool("ssh"), scp=config.tool("scp"))
        self._ssh, self._scp = commands.ssh, commands.scp
        self._platform = str(config.get("hardware.vitis.platform_name"))
        self._host = str(config.get("hardware.vitis.host_name"))
        self._names = (f"{self._platform}.bit", "ps7_init.tcl", f"{self._host}.elf")

    def programs(self) -> list[str]:
        return program_names(self._config)

    def upload(self) -> Step:
        workspace = vitis_workspace(self._config)
        files = (bitstream_path(self._config),
                 workspace / self._platform / "export" / self._platform / "hw/sdt/ps7_init.tcl",
                 workspace / self._host / "build" / f"{self._host}.elf")
        return Step(partial(self._copy, tuple(zip(files, self._names))), always_run=True)

    def upload_program(self, program: str) -> Step:
        memory = program_output(self._config, program, "_instructions.mem")
        return Step(partial(self._copy, ((memory, memory.name),)), always_run=True)

    def _copy(self, files: tuple[tuple[Path, str], ...]) -> None:
        """Copy files under explicit remote names, after checking that all of them exist."""
        bad = [name for _, name in files if not re.fullmatch(_NAME, name)]
        if bad:
            raise ValueError(f"Unsafe upload file names: {bad}")
        missing = [str(source) for source, _ in files if not source.is_file()]
        if missing:
            raise FileNotFoundError("Missing FPGA upload artifacts:\n" + "\n".join(missing))
        for source, name in files:
            remote = f"{self._s.upload.destination}:{PurePosixPath(self._s.upload.directory) / name}"
            print(f"Uploading {source} -> {remote}", flush=True)
            run([self._scp, "--", str(source), remote], cwd=self._config.repo_root)

    def _argv(self, remote_command: str) -> list[str]:
        return [self._ssh, "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "--", self._s.upload.destination, remote_command]

    def _shell(self, script: str, *, check_response: bool = False, select_device: bool = True) -> None:
        """Run the board machine's shell helpers, which only an interactive Bash loads."""
        selection = f"{shlex.join(['fuse', self._s.agent.device])} >/dev/null; " if select_device else ""
        argv = self._argv(shlex.join(["bash", "-ic", f"set -e; set -o pipefail; {selection}{script}"]))
        if not check_response:
            subprocess.run(argv, cwd=self._config.repo_root, check=True, text=True)
            return
        # The helpers can print {"detail": ...} for an agent error and still exit zero.
        lines = []
        with subprocess.Popen(argv, cwd=self._config.repo_root, stdout=subprocess.PIPE, text=True) as process:
            assert process.stdout is not None
            for line in process.stdout:
                print(line, end="", flush=True)
                lines.append(line)
            status = process.wait()
        text = "".join(lines)
        if status:
            raise subprocess.CalledProcessError(status, argv, output=text)
        decoder = json.JSONDecoder()
        for match in re.finditer(r"\{", text):
            try:
                response, _ = decoder.raw_decode(text, match.start())
            except json.JSONDecodeError:
                continue
            if isinstance(response, dict) and "detail" in response:
                raise RuntimeError(f"FPGA Agent rejected {script}: {response['detail']}")

    def reset(self) -> Step:
        # fr reads and keeps the current mode itself.
        return Step(partial(self._shell, shlex.join(["fr"])), always_run=True)

    def set_mode(self, mode: str) -> Step:
        return Step(partial(self._shell, shlex.join(["fm", mode])), always_run=True)

    def _preflight(self) -> None:
        """Read-only check of the uploaded files. Proves nothing about what the agent can see."""
        paths = [str(PurePosixPath(self._s.upload.directory) / name) for name in self._names]
        self._shell("missing=0; for artifact in " + shlex.join(paths) + "; do "
                    'if test -f "$artifact"; then :; else '
                    'printf "Missing FPGA uploaded artifact (not a file): %s\\n" "$artifact"; '
                    'missing=1; fi; done; exit "$missing"', select_device=False)

    def preflight(self) -> Step:
        return Step(self._preflight, always_run=True)

    def _program(self) -> None:
        # Separate checked sessions: an agent error from PL must stop PS.
        directory = PurePosixPath(self._s.agent.directory or self._s.upload.directory)
        bit, init, elf = (str(directory / name) for name in self._names)
        self._shell(shlex.join(["fpl", bit]), check_response=True)
        self._shell(shlex.join(["fps", init, elf]), check_response=True)

    def program(self) -> Step:
        return Step(self._program, always_run=True)

    def _uart(self, program: str, operation: str) -> None:
        """Stream the shared UART client and driver to Python on the board's machine."""
        uart = self._s.uart
        client = (self._config.repo_root / "tools/board/xc7z020/uart.py").read_text()
        driver = Path(__file__).with_name("program_uart.py").read_text()
        memory = str(PurePosixPath(self._s.upload.directory) / f"{program}_instructions.mem")
        # Separate exec scopes keep __future__ imports working without rewriting the client.
        payload = (f"exec({client!r}, globals())\nexec({driver!r}, globals())\n"
                   f"remote_main({operation!r}, {memory!r}, {uart.port!r}, {uart.baud!r})\n")
        remote = (["sudo", "-n"] if uart.sudo else []) + [uart.python, "-"]
        subprocess.run(self._argv(shlex.join(remote)), cwd=self._config.repo_root, input=payload, text=True, check=True)

    def load_program(self, program: str) -> Step:
        return Step(partial(self._uart, program, "load-imem"), always_run=True)

    def run_program(self, program: str) -> Step:
        return Step(partial(self._uart, program, "run"), always_run=True)
