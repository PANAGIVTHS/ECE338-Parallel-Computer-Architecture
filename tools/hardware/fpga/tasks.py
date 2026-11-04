"""Explicit board-VM operations on existing FPGA artifacts (no vendor builds)."""

from __future__ import annotations

import json
import re
import shlex
import subprocess
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from src.project_paths import ProjectPaths

if TYPE_CHECKING:
    from config import ResolvedConfig


def upload_artifacts(
    artifacts: tuple[tuple[Path, str], ...],
    command: str,
    destination: str,
    directory: str,
    cwd: Path,
    configured_names: tuple[tuple[str, Any], ...] = (),
) -> None:
    """Copy artifacts with explicit remote filenames using argv-based SCP."""
    if not isinstance(command, str) or not re.fullmatch(r"(?!-)[A-Za-z0-9_./-]+", command):
        raise ValueError("tools.scp.command must be a single nonempty executable without arguments")
    if not isinstance(destination, str) or not re.fullmatch(
        r"(?:[A-Za-z0-9_.][A-Za-z0-9_.-]*@)?[A-Za-z0-9_.][A-Za-z0-9_.-]*", destination
    ):
        raise ValueError("hardware.fpga.upload.destination must be a safe SSH hostname or user@hostname")
    if (
        not isinstance(directory, str)
        or not re.fullmatch(r"/[A-Za-z0-9_./-]*", directory)
        or any(part in (".", "..") for part in directory.split("/"))
    ):
        raise ValueError("hardware.fpga.upload.directory must be an absolute safe POSIX path without traversal")
    # Validate raw configured names as well as derived filenames: suffixing an
    # empty or non-string platform/host must not turn it into an accepted name.
    names = (*configured_names, *(("hardware.fpga.upload.filenames", filename) for _, filename in artifacts))
    for key, name in names:
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", name):
            raise ValueError(f"{key} must be a nonempty safe single basename without traversal")
    missing = [str(source) for source, _ in artifacts if not source.is_file()]
    if missing:
        raise FileNotFoundError("Missing FPGA upload artifacts:\n" + "\n".join(missing))
    for source, filename in artifacts:
        remote = f"{destination}:{PurePosixPath(directory) / filename}"
        print(f"Uploading {source} -> {remote}", flush=True)
        subprocess.run([command, "--", str(source), remote], cwd=cwd, check=True)


def _validated_string(config: ResolvedConfig, key: str, pattern: str, contract: str) -> str:
    value = config.get(key, None)
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise ValueError(f"{key} must be {contract}")
    return value


def _validated_path(config: ResolvedConfig, key: str) -> str:
    value = _validated_string(config, key, r"/[A-Za-z0-9_./-]*", "an absolute safe POSIX path without traversal")
    if any(part in (".", "..") for part in value.split("/")):
        raise ValueError(f"{key} must be an absolute safe POSIX path without traversal")
    return value


def run_shortcuts(
    config: ResolvedConfig, script: str, *, check_response: bool = False, select_device: bool = True,
) -> None:
    """Run installed VM shell helpers in an interactive Bash session."""
    command = _validated_string(config, "tools.ssh.command", r"(?!-)[A-Za-z0-9_./-]+", "a single nonempty executable without arguments")
    destination = _validated_string(
        config, "hardware.fpga.upload.destination",
        r"(?:[A-Za-z0-9_.][A-Za-z0-9_.-]*@)?[A-Za-z0-9_.][A-Za-z0-9_.-]*",
        "a safe SSH hostname or user@hostname",
    )
    device = _validated_string(config, "hardware.fpga.agent.device", r"[A-Za-z0-9_][A-Za-z0-9_.-]*", "a nonempty safe device identifier")
    selection = f"{shlex.join(['fuse', device])} >/dev/null; " if select_device else ""
    script = f"set -e; set -o pipefail; {selection}{script}"
    argv = [
        command, "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
        "--", destination, shlex.join(["bash", "-ic", script]),
    ]
    if not check_response:
        subprocess.run(argv, cwd=config.repo_root, check=True, text=True)
        return
    # Preserve live logs, but also inspect Agent HTTP-error bodies: the installed
    # shortcuts can print {"detail": ...} while returning shell exit status zero.
    output: list[str] = []
    with subprocess.Popen(argv, cwd=config.repo_root, stdout=subprocess.PIPE, text=True) as process:
        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="", flush=True)
            output.append(line)
        returncode = process.wait()
    response_text = "".join(output)
    if returncode:
        raise subprocess.CalledProcessError(returncode, argv, output=response_text)
    # Decode JSON objects even alongside helper banners or pretty-printed output.
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", response_text):
        try:
            response, _ = decoder.raw_decode(response_text, match.start())
        except json.JSONDecodeError:
            continue
        if isinstance(response, dict) and "detail" in response:
            raise RuntimeError(f"FPGA Agent rejected {script}: {response['detail']}")


def reset_board(config: ResolvedConfig) -> None:
    # fr itself reads and preserves the current mode, including lowercase modes.
    run_shortcuts(config, shlex.join(["fr"]))


def set_mode(config: ResolvedConfig, mode: str) -> None:
    if mode not in ("project", "demo"):
        raise ValueError("FPGA mode must be project or demo")
    run_shortcuts(config, shlex.join(["fm", mode]))


def _program_inputs(config: ResolvedConfig) -> tuple[str, tuple[str, str, str]]:
    """Validate the whole programming path/name batch before board prerequisites."""
    directory_key = (
        "hardware.fpga.upload.directory" if config.get("hardware.fpga.agent.directory") is None
        else "hardware.fpga.agent.directory"
    )
    directory = _validated_path(config, directory_key)
    platform = _validated_string(config, "hardware.vitis.platform_name", r"[A-Za-z0-9_][A-Za-z0-9_.-]*", "a nonempty safe single basename")
    host = _validated_string(config, "hardware.vitis.host_name", r"[A-Za-z0-9_][A-Za-z0-9_.-]*", "a nonempty safe single basename")
    return directory, (f"{platform}.bit", "ps7_init.tcl", f"{host}.elf")


def preflight_board(config: ResolvedConfig) -> None:
    """Read-only existence check of all uploaded VM files, not Agent mounts."""
    _, names = _program_inputs(config)
    upload_directory = _validated_path(config, "hardware.fpga.upload.directory")
    paths = [str(PurePosixPath(upload_directory) / name) for name in names]
    script = (
        "missing=0; for artifact in " + shlex.join(paths) + "; do "
        'if test -f "$artifact"; then :; else '
        'printf "Missing FPGA uploaded artifact (not a file): %s\\n" "$artifact"; '
        "missing=1; fi; done; exit \"$missing\""
    )
    run_shortcuts(config, script, select_device=False)


def program_board(config: ResolvedConfig) -> None:
    """After preflight, reset and PROJECT setup, program PL before PS."""
    directory, names = _program_inputs(config)
    pl = shlex.join(["fpl", str(PurePosixPath(directory) / names[0])])
    ps = shlex.join([
        "fps", str(PurePosixPath(directory) / names[1]),
        str(PurePosixPath(directory) / names[2]),
    ])
    # Separate checked responses ensure an HTTP error from PL prevents PS even
    # if the installed helper incorrectly returns a successful shell status.
    run_shortcuts(config, pl, check_response=True)
    run_shortcuts(config, ps, check_response=True)


def create_tasks(config: ResolvedConfig) -> list[dict[str, Any]]:
    """Create the independent FPGA task namespace, extensible with board commands."""
    paths = ProjectPaths.from_config(config)
    platform = config.get("hardware.vitis.platform_name")
    host = config.get("hardware.vitis.host_name")
    top = config.get("hardware.vivado.top")
    artifacts = (
        (paths.bitstream / f"{top}.bit", f"{platform}.bit"),
        (paths.vitis / f"{platform}" / "export" / f"{platform}" / "hw/sdt/ps7_init.tcl", "ps7_init.tcl"),
        (paths.vitis / f"{host}" / "build" / f"{host}.elf", f"{host}.elf"),
    )
    return [
        {
            "name": "fpga:upload",
            "task_dep": [],
            "uptodate": [False],
            "actions": [
                (
                    upload_artifacts,
                    [
                        artifacts,
                        config.get("tools.scp.command"),
                        config.get("hardware.fpga.upload.destination"),
                        config.get("hardware.fpga.upload.directory"),
                        paths.repo_root,
                        (("hardware.vitis.platform_name", platform), ("hardware.vitis.host_name", host)),
                    ],
                )
            ],
        },
        {
            "name": "fpga:reset", "task_dep": [], "uptodate": [False],
            "actions": [(reset_board, [config])],
        },
        {
            "name": "fpga:preflight", "task_dep": [], "uptodate": [False],
            "actions": [(preflight_board, [config])],
        },
        {
            "name": "fpga:program:reset", "task_dep": ["fpga:preflight"], "uptodate": [False],
            "actions": [(reset_board, [config])],
        },
        {
            # Setup runs after the preflight-scoped reset; standalone commands
            # remain independent of uploaded artifacts.
            "name": "fpga:program", "task_dep": ["fpga:program:reset"], "uptodate": [False],
            "setup": ["fpga:mode:project"],
            "actions": [(program_board, [config])],
        },
        {
            # Setup is scheduled only after upload succeeds, including for this
            # actionless aggregate. Reuse the unchanged program-only chain.
            "name": "fpga:deploy", "task_dep": ["fpga:upload"], "uptodate": [False],
            "setup": ["fpga:program"], "actions": [],
        },
        *[
            {
                "name": f"fpga:mode:{mode.lower()}", "task_dep": [], "uptodate": [False],
                "actions": [(set_mode, [config, mode])],
            }
            for mode in ("project", "demo")
        ],
        *_program_tasks(config, paths),
    ]


def run_program_uart(config: ResolvedConfig, program: str, operation: str) -> None:
    """Stream the shared UART client and driver to Python in the SSH namespace."""
    if operation not in ("load-imem", "run"):
        raise ValueError("Unknown UART operation")
    if not isinstance(program, str) or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", program):
        raise ValueError("Unsafe program basename")
    command = _validated_string(config, "tools.ssh.command", r"(?!-)[A-Za-z0-9_./-]+", "a single executable")
    destination = _validated_string(config, "hardware.fpga.upload.destination", r"(?:[A-Za-z0-9_.][A-Za-z0-9_.-]*@)?[A-Za-z0-9_.][A-Za-z0-9_.-]*", "a safe SSH destination")
    directory = _validated_path(config, "hardware.fpga.upload.directory")
    port = _validated_path(config, "hardware.fpga.uart.port")
    python = _validated_string(config, "hardware.fpga.uart.python", r"(?!-)[A-Za-z0-9_./-]+", "a single executable")
    baud = config.get("hardware.fpga.uart.baud")
    sudo = config.get("hardware.fpga.uart.sudo")
    if type(baud) is not int or baud <= 0:
        raise ValueError("hardware.fpga.uart.baud must be a positive integer")
    if type(sudo) is not bool:
        raise ValueError("hardware.fpga.uart.sudo must be boolean")
    remote = (["sudo", "-n"] if sudo else []) + [python, "-"]
    source_root = Path(__file__).resolve().parents[3]
    client = (source_root / "tools/board/xc7z020/uart.py").read_text()
    driver = Path(__file__).with_name("program_uart.py").read_text()
    # Separate exec scopes preserve __future__ imports without rewriting the client.
    imem = str(PurePosixPath(directory) / f"{program}_instructions.mem")
    payload = f"exec({client!r}, globals())\nexec({driver!r}, globals())\nremote_main({operation!r}, {imem!r}, {port!r}, {baud!r})\n"
    subprocess.run([command, "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "--", destination, shlex.join(remote)],
                   cwd=config.repo_root, input=payload, text=True, check=True)


def _program_tasks(config: ResolvedConfig, paths: ProjectPaths) -> list[dict[str, Any]]:
    tasks = []
    if not paths.software_programs.is_dir():
        return tasks
    import importlib.util

    # Task modules are loaded by file path; the checkout is not necessarily an
    # importable package (e.g. CLI invoked from another working directory).
    source = Path(__file__).resolve().parents[2] / "software/programs.py"
    spec = importlib.util.spec_from_file_location("fpga_software_programs", source)
    assert spec is not None and spec.loader is not None
    software = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(software)

    for program in software._program_names(paths.software_programs):
        prefix = f"fpga:programs:{program}"
        filename = f"{program}_instructions.mem"
        tasks.append({
            "name": f"{prefix}:upload",
            "task_dep": [f"software:programs:{program}:riscv:build", f"software:programs:{program}:mem"],
            "uptodate": [False],
            "actions": [(upload_artifacts, [
                ((paths.program_builds / program / filename, filename),),
                config.get("tools.scp.command"), config.get("hardware.fpga.upload.destination"),
                config.get("hardware.fpga.upload.directory"), paths.repo_root,
            ])],
        })
        for operation, dependency in (("load-imem", "upload"), ("run", "load-imem")):
            tasks.append({
                "name": f"{prefix}:{operation}", "task_dep": [f"{prefix}:{dependency}"],
                "uptodate": [False], "actions": [(run_program_uart, [config, program, operation])],
            })
        tasks.append({"name": f"{prefix}:all", "task_dep": [f"{prefix}:run"], "actions": []})
    return tasks
