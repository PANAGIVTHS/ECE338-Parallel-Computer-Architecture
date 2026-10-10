"""Real CLI/pydoit verification with a fake vendor in an isolated checkout.

This exercises orchestration and freshness, not Vivado synthesis.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest
from cli.cli import create_app
from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[4]
FAKE_VENDOR = r"""
import json
import sys
from pathlib import Path

args = sys.argv[1:]
script = Path(args[args.index('-source') + 1]).name
remaining = args[args.index('-tclargs') + 1:]
options = dict(zip(remaining[::2], remaining[1::2]))
project = Path(options['-project-dir'])
name, bd_name, top = (options[k] for k in ('-project-name', '-bd-name', '-top'))
bd = project / f'{name}.srcs/sources_1/bd/{bd_name}/{bd_name}.bd'
wrapper = project / f'{name}.gen/sources_1/bd/{bd_name}/hdl/{top}.v'
root = Path.cwd()
with (root / 'calls.jsonl').open('a') as output:
    output.write(json.dumps(script) + '\n')
def put(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
if script == 'create_project.tcl':
    put(project / f'{name}.xpr', 'project\n')
elif script == 'build_block_design.tcl':
    if not bd.exists():
        template = (root / 'tools/hardware/vivado/create_block_design.tcl').read_text()
        payload = next((json.loads(line.removeprefix('# saved-BD: ')) for line in template.splitlines() if line.startswith('# saved-BD: ')), 'default-design\n')
        put(bd, payload)
elif script == 'generate_block_design_wrapper.tcl':
    assert bd.is_file(), 'wrapper generation must have a prepared BD'
    put(wrapper, 'module stable_wrapper; endmodule\n')
elif script == 'export_block_design.tcl':
    if (root / 'fail-export').exists():
        print('deliberate export failure', file=sys.stderr)
        sys.exit(7)
    assert bd.is_file(), 'export needs an existing saved BD'
    text = '# CHANGE DESIGN NAME HERE\nvariable design_name\nset design_name ' + bd_name + '\n'
    text += 'set GPGPU_0 [create_bd_cell -type module -reference GPGPU GPGPU_0]\n'
    text += '# saved-BD: ' + json.dumps(bd.read_text()) + '\n'
    put(Path(options['-export-file']), text)
elif script == 'synthesis.tcl':
    put(project / f'{name}.runs/synth_1/{top}.dcp', 'synth:' + bd.read_text())
elif script == 'implementation.tcl':
    synth = project / f'{name}.runs/synth_1/{top}.dcp'
    put(project / f'{name}.runs/impl_1/{top}_routed.dcp', 'routed:' + synth.read_text())
elif script == 'bitstream.tcl':
    routed = project / f'{name}.runs/impl_1/{top}_routed.dcp'
    put(Path(options['-bitstream-dir']) / f'{top}.bit', 'bit:' + routed.read_text())
elif script == 'export_hardware.tcl':
    put(Path(options['-platform-dir']) / (options['-xsa-name'] + '.xsa'), 'xsa:' + bd.read_text())
else:
    raise AssertionError('Unexpected driver: ' + script)
"""


def checkout(tmp_path: Path) -> Path:
    repo = tmp_path / "checkout"
    for relative in (
        "hardware/rtl",
        "hardware/constraints",
        "software/host",
        "software/programs",
        "tests/hardware/rtl",
        "demo",
        "config/profiles",
    ):
        (repo / relative).mkdir(parents=True)
    shutil.copyfile(
        ROOT / "config/profiles/default.yaml", repo / "config/profiles/default.yaml"
    )
    shutil.copytree(ROOT / "tools/hardware/vivado", repo / "tools/hardware/vivado")
    for relative in (
        "tools/software/programs.py",
        "tools/tests/rtl.py",
        "tools/hardware/vitis/tasks.py",
        "tools/hardware/fpga/tasks.py",
    ):
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("def create_tasks(config):\n    return []\n")
    (repo / "hardware/rtl/GPGPU.v").write_text("module GPGPU; endmodule\n")
    (repo / "hardware/constraints/smart_zynq.xdc").write_text("# constraints\n")
    vendor = repo / "fake-vivado"
    vendor.write_text(f"#!{sys.executable}\n" + FAKE_VENDOR)
    vendor.chmod(0o755)
    return repo


def run(repo: Path, task: str = "vivado:all"):
    return CliRunner().invoke(
        create_app(repo_root=repo),
        [
            "--set",
            f"tools.vivado.command={repo / 'fake-vivado'}",
            "run",
            task,
            "--plain",
        ],
    )


def calls(repo: Path) -> list[str]:
    return [
        json.loads(line) for line in (repo / "calls.jsonl").read_text().splitlines()
    ]


def bd(repo: Path) -> Path:
    return (
        repo
        / "build/hardware/vivado/GPU/GPU.srcs/sources_1/bd/gpgpu_block_design/gpgpu_block_design.bd"
    )


def test_cli_bd_cold_then_warm_preserves_template_and_skips_expensive_builds(tmp_path):
    repo = checkout(tmp_path)
    result = run(repo)
    assert result.exit_code == 0, result.output
    assert calls(repo).index("build_block_design.tcl") < calls(repo).index(
        "generate_block_design_wrapper.tcl"
    )
    manifest = json.loads((repo / "logs/latest/run.json").read_text())
    names = [stage["task"] for stage in manifest["tasks"]]
    assert "vivado:block-design:build" in names
    assert "vivado:block-design:run" in names
    assert "vivado:block-design" not in names
    template = repo / "tools/hardware/vivado/create_block_design.tcl"
    # First warm invocation may normalize a newly created template.
    result = run(repo)
    assert result.exit_code == 0, result.output
    before = template.stat().st_mtime_ns
    offset = len(calls(repo))
    result = run(repo)
    assert result.exit_code == 0, result.output
    assert template.stat().st_mtime_ns == before
    assert "export_block_design.tcl" in calls(repo)[offset:]
    assert not set(calls(repo)[offset:]) & {
        "create_project.tcl",
        "synthesis.tcl",
        "implementation.tcl",
        "bitstream.tcl",
        "export_hardware.tcl",
    }


def test_cli_bd_gui_edit_with_same_wrapper_invalidates_hardware(tmp_path):
    repo = checkout(tmp_path)
    assert run(repo).exit_code == 0
    bd(repo).write_text("edited-GUI-design-with-more-settings\n")
    offset = len(calls(repo))
    result = run(repo)
    assert result.exit_code == 0, result.output
    assert bd(repo).read_text() == "edited-GUI-design-with-more-settings\n"
    assert (
        "edited-GUI-design-with-more-settings"
        in (repo / "tools/hardware/vivado/create_block_design.tcl").read_text()
    )
    assert "synthesis.tcl" in calls(repo)[offset:]
    assert "export_hardware.tcl" in calls(repo)[offset:]


def test_cli_bd_saved_gui_edit_survives_rtl_triggered_project_recreation(tmp_path):
    repo = checkout(tmp_path)
    assert run(repo).exit_code == 0
    bd(repo).write_text("saved-custom-GUI-design\n")
    (repo / "hardware/rtl/GPGPU.v").write_text(
        "module GPGPU; wire added_rtl_signal; endmodule\n"
    )
    offset = len(calls(repo))
    result = run(repo)
    assert result.exit_code == 0, result.output
    recent = calls(repo)[offset:]
    assert recent.index("export_block_design.tcl") < recent.index("create_project.tcl")
    assert bd(repo).read_text() == "saved-custom-GUI-design\n"


def test_cli_bd_build_stops_before_wrapper_and_run_generates_it(tmp_path):
    repo = checkout(tmp_path)
    result = run(repo, "vivado:block-design:build")
    assert result.exit_code == 0, result.output
    assert bd(repo).is_file()
    assert "generate_block_design_wrapper.tcl" not in calls(repo)
    result = run(repo, "vivado:block-design:run")
    assert result.exit_code == 0, result.output
    assert "generate_block_design_wrapper.tcl" in calls(repo)
    assert "synthesis.tcl" not in calls(repo)


def test_cli_removed_bd_commands_do_not_invoke_vendor(tmp_path):
    repo = checkout(tmp_path)
    for name in (
        "vivado:block-design",
        "vivado:extract-block-design",
        "vivado:export-block-design",
    ):
        result = run(repo, name)
        assert result.exit_code != 0, result.output
    assert not (repo / "calls.jsonl").exists()


@pytest.mark.parametrize(
    ("project_present", "alternate_location"),
    [(False, False), (False, True), (True, True)],
)
def test_cli_orphan_saved_bd_is_not_deleted(
    tmp_path, project_present, alternate_location
):
    repo = checkout(tmp_path)
    project = repo / "build/hardware/vivado/GPU"
    saved_bd = project / "saved_gui_design.bd" if alternate_location else bd(repo)
    saved_bd.parent.mkdir(parents=True)
    saved_bd.write_text("orphan-saved-design\n")
    if project_present:
        (project / "GPU.xpr").write_text("existing-project\n")
    result = run(repo, "vivado:block-design:build")
    assert result.exit_code != 0, result.output
    assert saved_bd.read_text() == "orphan-saved-design\n"
    if (repo / "calls.jsonl").exists():
        assert "create_project.tcl" not in calls(repo)


def test_cli_bd_preservation_failure_keeps_project_and_template(tmp_path):
    repo = checkout(tmp_path)
    assert run(repo).exit_code == 0
    saved = bd(repo).read_text()
    template = repo / "tools/hardware/vivado/create_block_design.tcl"
    old_template = template.read_bytes()
    (repo / "hardware/rtl/GPGPU.v").write_text(
        "module GPGPU; wire new_signal; endmodule\n"
    )
    (repo / "fail-export").touch()
    offset = len(calls(repo))
    result = run(repo)
    assert result.exit_code != 0
    assert "create_project.tcl" not in calls(repo)[offset:]
    assert bd(repo).read_text() == saved
    assert template.read_bytes() == old_template
