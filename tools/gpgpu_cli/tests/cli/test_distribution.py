from __future__ import annotations

import os
from pathlib import Path
import subprocess

import yaml


REPO_ROOT = Path(__file__).resolve().parents[4]
CLI_PROJECT = REPO_ROOT / "tools/gpgpu_cli"


def test_configuration_modules_live_in_config_package() -> None:
    assert (CLI_PROJECT / "config/__init__.py").is_file()
    assert (CLI_PROJECT / "config/config.py").is_file()
    assert (CLI_PROJECT / "config/paths.py").is_file()
    assert not (CLI_PROJECT / "cli/config.py").exists()
    assert not (CLI_PROJECT / "cli/paths.py").exists()


def test_repository_has_default_profile_and_local_override_template() -> None:
    profile_path = REPO_ROOT / "config/profiles/default.yaml"
    template_path = REPO_ROOT / "config/local.yaml.example"

    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    assert profile["paths"] == {"build": {"root": "build"}}
    assert profile["hardware"]["vivado"]["project_name"] == "gpgpu_system"
    assert profile["hardware"]["vivado"]["ip_project_name"] == "gpgpu_ip_dev"
    assert profile["hardware"]["vivado"]["bd_name"] == "design_1"
    assert profile["hardware"]["vivado"]["top"] == "design_1_wrapper"
    assert profile["hardware"]["vivado"]["xsa_name"] == "gpgpu_platform"
    assert profile["hardware"]["vivado"]["version"] == "2025.2"
    assert profile["hardware"]["vivado"]["peripheral"] == {
        "base_address": "0x43C00000", "range": "0x00010000",
    }
    assert "host_interface" not in profile["hardware"]["vivado"]
    assert profile["tools"]["vivado"]["required"] is False
    assert profile["tests"]["rtl"]["random"]["iterations"] == 100
    assert profile["tests"]["rtl"]["random"]["seed"] == 0
    assert template_path.is_file()


def test_root_launcher_is_executable_and_runs_cli(tmp_path: Path) -> None:
    import shutil
    import sys
    repo = tmp_path / 'launcher-checkout'
    repo.mkdir()
    launcher = repo / 'gpgpu'
    shutil.copy2(REPO_ROOT / 'gpgpu', launcher)
    shutil.copytree(REPO_ROOT / 'config', repo / 'config', ignore=shutil.ignore_patterns('local.yaml'))
    (repo / 'tools/gpgpu_cli').mkdir(parents=True)
    (repo / 'hardware/rtl').mkdir(parents=True)
    # Exercise the real launcher, never the shared environment/bootstrap.
    entry = repo / '.venv/bin/gpgpu'
    entry.parent.mkdir(parents=True)
    entry.write_text(f'#!{sys.executable}\nfrom cli.cli import main\nmain()\n')
    entry.chmod(0o755)

    assert os.access(launcher, os.X_OK)
    launcher_text = launcher.read_text(encoding="utf-8")
    assert 'CLI_PROJECT="$ROOT/tools/gpgpu_cli"' in launcher_text
    assert 'uv sync --project "$CLI_PROJECT"' in launcher_text
    assert '--editable "$ROOT/tools/gpgpu_tasks"' in launcher_text
    assert '--editable "$CLI_PROJECT"' in launcher_text
    assert "uv sync" in launcher_text
    assert "--extra" not in launcher_text
    assert "[dev]" not in launcher_text
    assert '"${1:-}" == "init"' not in launcher_text
    assert '"$VENV/bin/gpgpu" doctor' in launcher_text
    result = subprocess.run(
        [str(launcher), "config", "get", "architecture.num_cores"],
        cwd=repo / "hardware/rtl",
        check=True,
        capture_output=True,
        text=True,
    )
    assert "24" in result.stdout



def test_root_launcher_rebuilds_a_relocated_virtualenv_and_runs_requested_command(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    launcher = repo / "gpgpu"
    launcher.write_text((REPO_ROOT / "gpgpu").read_text(encoding="utf-8"), encoding="utf-8")
    launcher.chmod(0o755)
    (repo / "tools/gpgpu_cli").mkdir(parents=True)
    (repo / "config").mkdir()

    stale_cli = repo / ".venv/bin/gpgpu"
    stale_cli.parent.mkdir(parents=True)
    stale_cli.write_text(
        "#!/workspace/old-location/.venv/bin/python\nprint('stale')\n",
        encoding="utf-8",
    )
    stale_cli.chmod(0o755)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_uv = fake_bin / "uv"
    fake_uv.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "mkdir -p \"$UV_PROJECT_ENVIRONMENT/bin\"\n"
        "cat > \"$UV_PROJECT_ENVIRONMENT/bin/gpgpu\" <<'EOF'\n"
        "#!/usr/bin/env bash\n"
        "if [[ \"${1:-}\" == doctor ]]; then exit 0; fi\n"
        "printf 'executed:%s\\n' \"$*\"\n"
        "EOF\n"
        "chmod +x \"$UV_PROJECT_ENVIRONMENT/bin/gpgpu\"\n",
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    result = subprocess.run(
        [str(launcher), "run", "tests:rtl:generate"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "Running first-time initialization" in result.stdout
    assert "executed:run tests:rtl:generate" in result.stdout
