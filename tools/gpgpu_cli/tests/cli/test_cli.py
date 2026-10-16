from __future__ import annotations

import json
from pathlib import Path

import cli.commands.run as run_command_module
import pytest
from cli.cli import create_app
from typer.testing import CliRunner

runner = CliRunner()


def make_repo(tmp_path: Path) -> Path:
    profiles = tmp_path / "config/profiles"
    profiles.mkdir(parents=True)
    (profiles / "default.yaml").write_text(
        """
project:
  name: test-gpgpu
paths:
  build:
    root: build
tools:
  python:
    command: python3
    required: true
  optional_missing:
    command: command-that-does-not-exist-gpgpu-test
    required: false
""",
        encoding="utf-8",
    )
    for relative in (
        "hardware/rtl",
        "hardware/constraints",
        "software/host",
        "software/programs",
        "tests/hardware/rtl",
        "demo",
    ):
        (tmp_path / relative).mkdir(parents=True)
    return tmp_path


def test_config_show_uses_global_profile_and_cli_overrides(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    app = create_app(repo_root=repo)

    result = runner.invoke(
        app,
        ["--profile", "default", "--set", "project.name=overridden", "config", "show", "--format", "json"],
    )

    assert result.exit_code == 0, result.output
    document = json.loads(result.stdout)
    assert document["project"]["name"] == "overridden"


def test_config_get_reports_value_and_source(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    app = create_app(repo_root=repo)

    result = runner.invoke(app, ["config", "get", "project.name", "--source"])

    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines()[0] == "test-gpgpu"
    assert "..." not in result.stdout
    assert "config/profiles/default.yaml" in result.stdout


def test_config_get_resolves_build_root_for_external_consumers(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    app = create_app(repo_root=repo)

    result = runner.invoke(
        app,
        ["--set", "paths.build.root=external-build", "config", "get", "paths.build.root", "--resolved-path"],
    )

    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == str((repo / "external-build").resolve())


def test_doctor_distinguishes_required_and_optional_tools(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    app = create_app(repo_root=repo)

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0, result.output
    assert "python" in result.stdout
    assert "optional_missing" in result.stdout
    assert "MISSING (optional)" in result.stdout
    assert "paths.build.root" in result.stdout
    assert "NOT BUILT" in result.stdout
    assert "Errors: 0" in result.stdout
    assert "Warnings: 1" in result.stdout


def test_config_validate_accepts_partial_profile_inheriting_default(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    (repo / "config/profiles/incomplete.yaml").write_text(
        "project:\n  name: incomplete\n",
        encoding="utf-8",
    )
    app = create_app(repo_root=repo)

    result = runner.invoke(app, ["--profile", "incomplete", "config", "validate"])

    assert result.exit_code == 0, result.output
    assert "Errors: 0" in result.stdout


def test_doctor_does_not_duplicate_config_structure_errors(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    (repo / "config/local.yaml").write_text("tools: invalid\n", encoding="utf-8")
    app = create_app(repo_root=repo)

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 1, result.output
    assert result.stdout.count("tools must be a mapping") == 1
    assert "The 'tools' configuration option must be a mapping" not in result.stdout
    assert "Errors: 1" in result.stdout


def test_callback_fails_immediately_on_config_parse_error(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    (repo / "config/profiles/broken.yaml").write_text("project: [\n", encoding="utf-8")
    app = create_app(repo_root=repo)

    result = runner.invoke(app, ["--profile", "broken", "doctor"])

    assert result.exit_code == 2, result.output
    assert "Invalid YAML" in result.stderr
    assert "GPGPU environment" not in result.stdout
    assert "Summary" not in result.stdout


def test_doctor_counts_missing_required_repository_paths_as_errors(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    (repo / "hardware/rtl").rmdir()
    app = create_app(repo_root=repo)

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 1, result.output
    assert "Repository path is missing: repository.hardware.rtl" in result.stdout
    assert "Errors: 1" in result.stdout


def test_doctor_rejects_repository_paths_that_are_not_directories(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    (repo / "demo").rmdir()
    (repo / "demo").write_text("not a directory\n", encoding="utf-8")

    result = runner.invoke(create_app(repo_root=repo), ["doctor"])

    assert result.exit_code == 1, result.output
    assert "Repository path is not a directory: repository.demo" in result.stdout


def test_doctor_rejects_build_root_that_is_not_a_directory(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    (repo / "build").write_text("not a directory\n", encoding="utf-8")

    result = runner.invoke(create_app(repo_root=repo), ["doctor"])

    assert result.exit_code == 1, result.output
    assert "Build root is not a directory" in result.stdout


def test_run_dispatches_exactly_one_task_with_resolved_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = make_repo(tmp_path)
    captured: dict[str, object] = {}

    def fake_run(config: object, task: str) -> int:
        captured["config"] = config
        captured["task"] = task
        return 0

    monkeypatch.setattr(run_command_module, "run_logged_task", fake_run)
    result = runner.invoke(
        create_app(repo_root=repo),
        ["run", "software:programs:simple:x86"],
    )

    assert result.exit_code == 0, result.output
    assert captured["task"] == "software:programs:simple:x86"
    assert captured["config"].profile == "default"  # type: ignore[union-attr]


def test_run_plain_disables_monitor_without_changing_task_or_exit_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    def fake_run(config: object, task: str, *, monitor: bool | None = None) -> int:
        captured.update(task=task, monitor=monitor)
        return 2

    monkeypatch.setattr(run_command_module, "run_logged_task", fake_run)
    result = runner.invoke(create_app(repo_root=make_repo(tmp_path)), ["run", "demo:all", "--plain"])

    assert result.exit_code == 2, result.output
    assert captured == {"task": "demo:all", "monitor": False}


def test_run_rejects_build_root_overlap_before_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = make_repo(tmp_path)
    dispatched = False

    def fake_run(config: object, task: str) -> int:
        nonlocal dispatched
        dispatched = True
        return 0

    monkeypatch.setattr(run_command_module, "run_logged_task", fake_run)
    result = runner.invoke(
        create_app(repo_root=repo),
        ["--set", "paths.build.root=.", "run", "software:programs:simple:x86"],
    )

    assert result.exit_code != 0, result.output
    assert "must not be the repository root" in result.output
    assert not dispatched


def test_run_propagates_pydoit_failure_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run_command_module, "run_logged_task", lambda config, task: 3)

    result = runner.invoke(create_app(repo_root=make_repo(tmp_path)), ["run", "missing"])

    assert result.exit_code == 3


def test_run_help_explains_task_names_and_common_workflows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COLUMNS", "160")
    result = runner.invoke(create_app(repo_root=make_repo(tmp_path)), ["run", "--help"])

    assert result.exit_code == 0, result.output
    arguments_index = result.stdout.index("Arguments")
    possible_values_index = result.stdout.index("Possible values")
    assert arguments_index < possible_values_index
    assert "software:programs:" not in result.stdout[:arguments_index]
    assert "colon-separated" in result.stdout
    programs_index = result.stdout.index("Programs")
    tests_index = result.stdout.index("Tests")
    assert arguments_index < programs_index < tests_index
    assert "software:programs:<program>:x86" in result.stdout
    assert "software:programs:<program>:x86:build" in result.stdout
    assert "software:programs:<program>:riscv:build" in result.stdout
    assert "software:programs:<program>:elf" in result.stdout
    assert "software:programs:<program>:mem" in result.stdout
    assert "software:programs:<program>:all" in result.stdout
    assert "software:programs:simple:x86" in result.stdout
    assert "native x86 executable" in result.stdout
    assert "tests:rtl:generate" in result.stdout
    assert "tests:rtl:e2e:build" in result.stdout
    assert "tests:rtl:e2e:run" in result.stdout
    assert "tests:rtl:e2e:all" in result.stdout
    assert "tests:rtl:smx:build" in result.stdout
    assert "tests:rtl:smx:run" in result.stdout
    assert "tests:rtl:smx:all" in result.stdout
    assert "tests:rtl:random" in result.stdout
    assert "tests.rtl.random.iterations" in result.stdout
    assert "tests.rtl.random.seed" in result.stdout
    assert "tests:rtl:build" in result.stdout
    assert "tests:rtl:run" in result.stdout
    assert "tests:rtl:all" in result.stdout
    assert "end-to-end" in result.stdout
    assert "SMX-only" in result.stdout
    vivado_index = result.stdout.index("Vivado")
    assert tests_index < vivado_index
    for task in ('vivado:ip:create', 'vivado:ip:build', 'vivado:system:create', 'vivado:system:build'):
        assert task in result.stdout
    assert 'vivado:project' not in result.stdout
    assert 'vivado:xsa' not in result.stdout
    assert 'dependency chain' in result.stdout


@pytest.mark.parametrize("width", [80, 120, 180])
def test_run_help_aligns_task_descriptions_in_table_columns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, width: int
) -> None:
    monkeypatch.setenv("COLUMNS", str(width))
    result = runner.invoke(create_app(repo_root=make_repo(tmp_path)), ["run", "--help"])

    assert result.exit_code == 0, result.output
    assert "Command" in result.stdout and "Description" in result.stdout
    lines = result.stdout.splitlines()
    build_line = next(line for line in lines if "software:programs:<program>:x86:build" in line)
    run_line = next(line for line in lines if "software:programs:<program>:x86 " in line)
    assert build_line.index("Build") == run_line.index("Build")
    # Long descriptions stay in the right column, not underneath task names.
    continuation = next(line for line in lines if "without running" in line)
    assert continuation.index("without") >= build_line.index("Build")
    assert all(len(line) <= width for line in lines)
    assert "•" not in result.stdout


def test_run_help_renders_code_references_without_literal_backticks(tmp_path: Path) -> None:
    result = runner.invoke(create_app(repo_root=make_repo(tmp_path)), ["run", "--help"])

    assert result.exit_code == 0
    assert "`" not in result.stdout
    assert "fpga:upload" in result.stdout
    assert "hardware.fpga.upload.destination" in result.stdout


def test_task_help_highlights_task_names_separately_from_references() -> None:
    from rich.console import Console
    from rich.text import Text

    console = Console()
    markup = run_command_module._format_task_help(
        "• `fpga:upload` — Configure `hardware.fpga.upload.directory`. "
        "Example: `software:programs:<program>:x86`"
    )
    rendered = Text.from_markup(markup)
    task_style = rendered.get_style_at_offset(console, rendered.plain.index("fpga:upload"))
    reference_style = rendered.get_style_at_offset(console, rendered.plain.index("hardware.fpga"))
    example_style = rendered.get_style_at_offset(console, rendered.plain.index("software:programs"))
    assert task_style.color is not None
    assert example_style.color is not None
    assert reference_style.color is not None
    assert task_style.bold and task_style.color.name == "bright_green"
    assert example_style.bold and example_style.color.name == "bright_green"
    assert reference_style.color.name == "yellow"


@pytest.mark.parametrize("source", ["default", "profile", "local", "cli"])
def test_run_help_uses_resolved_upload_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str
) -> None:
    monkeypatch.setenv("COLUMNS", "180")
    repo = make_repo(tmp_path)
    default = repo / "config/profiles/default.yaml"
    default.write_text(
        default.read_text() + "\nhardware:\n  fpga:\n    upload:\n"
        "      destination: base@board\n      directory: /base/upload\n"
    )
    destination = f"{source}@board"
    directory = f"/{source}/upload"
    layer = {"hardware": {"fpga": {"upload": {
        "destination": destination, "directory": directory,
    }}}}
    arguments = []
    if source == "profile":
        (repo / "config/profiles/board.yaml").write_text(json.dumps(layer))
        arguments = ["--profile", "board"]
    elif source == "local":
        (repo / "config/local.yaml").write_text(json.dumps(layer))
    elif source == "cli":
        arguments = [
            "--set", f"hardware.fpga.upload.destination={destination}",
            "--set", f"hardware.fpga.upload.directory={directory}",
        ]
    else:
        destination, directory = "base@board", "/base/upload"

    result = runner.invoke(create_app(repo_root=repo), arguments + ["run", "--help"])

    assert result.exit_code == 0, result.output
    assert "Configured values:" in result.stdout
    assert destination in result.stdout
    assert directory in result.stdout
    assert "njason@192.168.1.13" not in result.stdout
    assert "/home/njason/upload" not in result.stdout
    assert "defaults:" not in result.stdout


def test_run_help_lists_fpga_upload_as_explicit_existing_artifact_operation(tmp_path: Path) -> None:
    result = runner.invoke(create_app(repo_root=make_repo(tmp_path)), ["run", "--help"])

    assert result.exit_code == 0
    assert "FPGA" in result.stdout
    assert "fpga:upload" in result.stdout
    assert "without building" in result.stdout


def test_vitis_platform_help_describes_xsa_not_bitstream() -> None:
    help_text = run_command_module._TASK_HELP
    description = next(line for line in help_text.splitlines() if "`vitis:build:platform`" in line)

    assert "`.xsa`" in description
    assert "`.bit`" not in description
    assert "ps7_init.tcl" in description


def test_help_exposes_core_commands_and_completion_flags(tmp_path: Path) -> None:
    app = create_app(repo_root=make_repo(tmp_path))

    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0, result.output
    assert "init" not in result.stdout
    assert "doctor" in result.stdout
    assert "config" in result.stdout
    assert "run" in result.stdout
    assert "--install-completion" in result.stdout
    assert "--show-completion" in result.stdout


def test_command_handlers_live_in_commands_package() -> None:
    package = Path(__file__).resolve().parents[2] / "cli"
    entrypoint = (package / "cli.py").read_text(encoding="utf-8")

    assert (package / "commands/__init__.py").is_file()
    assert (package / "commands/doctor.py").is_file()
    assert (package / "commands/config.py").is_file()
    assert (package / "commands/run.py").is_file()
    assert "def doctor(" not in entrypoint
    assert "def config_show(" not in entrypoint
    assert "def config_get(" not in entrypoint
    assert "def config_validate(" not in entrypoint
