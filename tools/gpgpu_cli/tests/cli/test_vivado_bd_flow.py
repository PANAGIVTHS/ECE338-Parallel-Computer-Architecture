"""Real CLI/pydoit orchestration with explicitly FAKE vendor processes.

Disposable checkouts only. Does not claim Vivado/Vitis compatibility or hardware
success; real Tcl/API contracts are tested separately.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys

from cli.cli import create_app
from config import resolve_config
from src.doit import create_task_loader
from doit.control import TaskControl
from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[4]
FAKE_VENDOR = r'''
import json, runpy, shutil, sys, zipfile
from pathlib import Path
args = sys.argv[1:]
if args == ['-version']:
    print('FAKE Vivado 2025.2 -- orchestration fixture, not vendor verification')
    raise SystemExit(0)
def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value)
if '-source' in args:
    script = Path(args[args.index('-source') + 1]).name
    raw = args[args.index('-tclargs') + 1:]
    options = dict(zip(raw[::2], raw[1::2]))
    project = Path(options['-project-dir'])
    name, bdname, top = (options[k] for k in ('-project-name', '-bd-name', '-top'))
    root = Path(options['-bitstream-dir']).parents[1]
    repo = Path(options['-repo-root'])
    calls = root / 'calls.jsonl'
    with calls.open('a') as f: f.write(json.dumps(script) + '\n')
    if script == 'create_ip_project.tcl':
        put(project / f'{name}.xpr', 'FAKE IP project')
    elif script == 'package_ip.tcl':
        if (root / 'FAIL_PACKAGE').exists():
            print('FAKE deliberate package failure')
            raise SystemExit(7)
        fixture = runpy.run_path(str(repo / 'tools/gpgpu_tasks/tests/test_ip_packaging.py'))
        fixture['package_fixture'](Path(options['-ip-repo-dir']))
    elif script == 'create_system.tcl':
        bd = project / f'{name}.srcs/sources_1/bd/{bdname}/{bdname}.bd'
        data = json.loads(bd.read_text()) if bd.exists() else {'design': {
            'design_info': {'name': bdname, 'device': options['-part']},
            'components': {'processing_system7_0': {}, 'axi_smc': {},
                           'gpgpu_axi_0': {'vlnv': 'user.org:user:gpgpu_axi:1.0'}}}}
        data['config'] = {'cores': options['-num-cores'], 'base': options['-axi-base']}
        data['package'] = (Path(options['-ip-repo-dir']) / '.gpgpu-package.json').read_text()
        put(bd, json.dumps(data, sort_keys=True))
        put(project / f'{name}.xpr', 'FAKE system project')
        put(project / f'{name}.gen/sources_1/bd/{bdname}/hdl/{top}.v', 'FAKE stable wrapper')
    elif script == 'synthesis.tcl':
        bd = project / f'{name}.srcs/sources_1/bd/{bdname}/{bdname}.bd'
        ip_content = ''.join(p.read_text() for p in sorted(project.rglob('*.xci')))
        put(project / f'{name}.runs/synth_1/{top}.dcp', 'FAKE synth ' + bd.read_text() + Path(options['-xdc-file']).read_text() + ip_content)
    elif script == 'implementation.tcl':
        put(project / f'{name}.runs/impl_1/{top}_routed.dcp', 'FAKE route ' + (project / f'{name}.runs/synth_1/{top}.dcp').read_text())
    elif script == 'bitstream.tcl':
        if (root / 'FAIL_BIT').exists(): raise SystemExit(8)
        put(Path(options['-bitstream-dir']) / f'{top}.bit', 'FAKE bit ' + (project / f'{name}.runs/impl_1/{top}_routed.dcp').read_text())
    elif script == 'export_hardware.tcl':
        target = Path(options['-platform-dir']) / f"{options['-xsa-name']}.xsa"
        target.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(target, 'w') as archive:
            for name in ['system.bit','system.hwh','ps7_init.tcl','ps7_init.c']:
                archive.writestr(name, 'FAKE XSA ' + (Path(options['-bitstream-dir']) / f'{top}.bit').read_text())
    else: raise RuntimeError(script)
else:
    raw = args[args.index('--') + 1:]
    action, raw = raw[0], raw[1:]
    options = dict(zip(raw[::2], raw[1::2]))
    workspace = Path(options['--workspace'])
    root = workspace.parents[1]
    with (root / 'calls.jsonl').open('a') as f: f.write(json.dumps('vitis:' + action) + '\n')
    if action == 'project':
        platform = options['--platform']
        put(workspace / platform / 'vitis-comp.json', json.dumps({'name': platform, 'hw': options['--xsa']}))
    elif action == 'build':
        platform = options['--component']
        exported = workspace / platform / f'export/{platform}'
        metadata = json.loads((workspace / platform / 'vitis-comp.json').read_text())
        target = exported / f'hw/{platform}.xsa'; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(metadata['hw'], target)
        put(exported / 'hw/sdt/ps7_init.tcl', 'FAKE PS init ' + target.read_bytes().hex())
        put(exported / f'{platform}.xpfm', 'FAKE XPFM ' + target.read_bytes().hex())
    elif action == 'host':
        host = options['--component']; platform = options['--platform']
        root = workspace / host
        put(root / 'vitis-comp.json', json.dumps({'name': host}))
        put(root / f'build/{host}.elf', 'FAKE ELF ' + (workspace / platform / f'export/{platform}/{platform}.xpfm').read_text() + json.dumps(options))
    else: raise RuntimeError(action)
print('FAKE vendor stage completed (orchestration only)', flush=True)
'''


def checkout(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    for name in ('tools', 'hardware', 'software', 'tests', 'config'):
        shutil.copytree(ROOT / name, repo / name,
                        ignore=shutil.ignore_patterns('__pycache__', '.pytest_cache', '.venv', 'local.yaml'))
    shutil.copyfile(ROOT / 'gpgpu', repo / 'gpgpu')
    fake = repo / 'fake-vendor'
    fake.write_text(f'#!{sys.executable}\n' + FAKE_VENDOR)
    fake.chmod(0o755)
    (repo / 'config/local.yaml').write_text(f'tools:\n  vivado:\n    command: {fake}\n  vitis:\n    command: {fake}\n')
    return repo


def run(repo, task='vitis:build:all', *overrides):
    arguments = [item for value in overrides for item in ('--set', value)]
    return CliRunner().invoke(create_app(repo_root=repo), [*arguments, 'run', task, '--plain'])


def calls(repo):
    file = repo / 'build/calls.jsonl'
    return [json.loads(line) for line in file.read_text().splitlines()] if file.exists() else []


CHAIN = ['create_ip_project.tcl', 'package_ip.tcl', 'create_system.tcl', 'synthesis.tcl',
         'implementation.tcl', 'bitstream.tcl', 'export_hardware.tcl',
         'vitis:project', 'vitis:build', 'vitis:host']


def test_clean_bootstrap_full_effective_graph_and_unchanged_cache(tmp_path):
    repo = checkout(tmp_path)
    assert not (repo / 'build').exists()
    tasks = create_task_loader(resolve_config(repo)).load_tasks(None, [])
    control = TaskControl(tasks)  # Detect implicit file edges and cycles in the real loader.
    assert 'vivado:system:build' in control.tasks['vitis:project'].task_dep
    assert 'vitis:build:host' in control.tasks['vitis:build:all'].task_dep
    result = run(repo)
    assert result.exit_code == 0, result.output
    assert calls(repo) == CHAIN
    second = run(repo)
    assert second.exit_code == 0, second.output
    assert calls(repo) == CHAIN
    assert (repo / 'build/software/vitis/gpgpu_host/build/gpgpu_host.elf').exists()


def test_saved_gui_state_survives_source_repackaging_and_same_wrapper(tmp_path):
    repo = checkout(tmp_path)
    assert run(repo).exit_code == 0
    bd = repo / 'build/hardware/vivado/gpgpu_system/gpgpu_system.srcs/sources_1/bd/design_1/design_1.bd'
    data = json.loads(bd.read_text()); data['gui'] = 'retain'; bd.write_text(json.dumps(data))
    result = run(repo)
    assert result.exit_code == 0, result.output
    assert calls(repo)[len(CHAIN):] == CHAIN[3:]
    source = repo / 'hardware/rtl/gpgpu/constants.svh'
    source.write_text(source.read_text() + '\n// isolated freshness probe\n')
    previous = len(calls(repo))
    result = run(repo)
    assert result.exit_code == 0, result.output
    assert calls(repo)[previous:] == CHAIN
    assert json.loads(bd.read_text())['gui'] == 'retain'
    assert list((repo / 'build/hardware/vivado/.snapshots').iterdir())


def test_configuration_xdc_and_host_header_invalidation(tmp_path):
    repo = checkout(tmp_path)
    assert run(repo).exit_code == 0
    values = ('architecture.num_cores=4', 'hardware.vivado.peripheral.base_address="0x44000000"')
    previous = len(calls(repo))
    result = run(repo, 'vitis:build:all', *values)
    assert result.exit_code == 0, result.output
    assert calls(repo)[previous:] == CHAIN
    xdc = repo / 'hardware/constraints/smart_zynq.xdc'
    xdc.write_text(xdc.read_text() + '\n# isolated XDC probe\n')
    previous = len(calls(repo))
    result = run(repo, 'vitis:build:all', *values)
    assert result.exit_code == 0, result.output
    assert calls(repo)[previous:] == CHAIN[2:]
    header = repo / 'software/host/xc7z020/gpgpu_driver.h'
    header.write_text(header.read_text() + '\n// isolated header probe\n')
    previous = len(calls(repo))
    result = run(repo, 'vitis:build:all', *values)
    assert result.exit_code == 0, result.output
    assert calls(repo)[previous:] == ['vitis:host']


def test_packaging_failure_blocks_system_and_vitis_publication(tmp_path):
    repo = checkout(tmp_path)
    root = repo / 'build'; root.mkdir(); (root / 'FAIL_PACKAGE').write_text('intentional')
    result = run(repo)
    assert result.exit_code != 0
    assert calls(repo) == CHAIN[:2]
    assert not (root / 'hardware/vivado/ip_repo/component.xml').exists()
    assert not (root / 'software/vitis').exists()
    assert 'failed with exit 7' in result.output


def test_failed_bitstream_retry_keeps_routed_state(tmp_path):
    repo = checkout(tmp_path)
    root = repo / 'build'; root.mkdir(); (root / 'FAIL_BIT').write_text('intentional')
    result = run(repo)
    assert result.exit_code != 0
    assert calls(repo) == CHAIN[:6]
    route = root / 'hardware/vivado/gpgpu_system/gpgpu_system.runs/impl_1/design_1_wrapper_routed.dcp'
    before = route.stat().st_mtime_ns
    (root / 'FAIL_BIT').unlink()
    previous = len(calls(repo))
    result = run(repo)
    assert result.exit_code == 0, result.output
    assert calls(repo)[previous:] == CHAIN[5:]
    assert route.stat().st_mtime_ns == before


def test_xci_edit_with_same_bd_wrapper_invalidates_synthesis(tmp_path):
    repo = checkout(tmp_path)
    assert run(repo).exit_code == 0
    xci = repo / 'build/hardware/vivado/gpgpu_system/gpgpu_system.srcs/sources_1/ip/core.xci'
    xci.parent.mkdir(parents=True); xci.write_text('FAKE isolated GUI IP change')
    previous = len(calls(repo))
    result = run(repo)
    assert result.exit_code == 0, result.output
    assert calls(repo)[previous:] == CHAIN[3:]
    previous = len(calls(repo))
    assert run(repo).exit_code == 0
    assert len(calls(repo)) == previous


def test_package_tampering_and_xgui_metadata_republish_before_consumers(tmp_path):
    repo = checkout(tmp_path)
    assert run(repo).exit_code == 0
    package = repo / 'build/hardware/vivado/ip_repo'
    metadata = json.loads((package / '.gpgpu-package.json').read_text())
    assert metadata['revision'] == 1
    source = package / 'src/GPGPU.sv'
    source.write_text('FAKE tampered package, must not be trusted')
    previous = len(calls(repo))
    result = run(repo)
    assert result.exit_code == 0, result.output
    assert calls(repo)[previous:] == CHAIN[1:]
    assert json.loads((package / '.gpgpu-package.json').read_text())['revision'] == 2
    xgui = repo / 'tools/hardware/vivado/ip/xgui/gpgpu_axi_v1_0.tcl'
    xgui.write_text(xgui.read_text() + '\n# isolated metadata probe\n')
    previous = len(calls(repo))
    result = run(repo)
    assert result.exit_code == 0, result.output
    assert calls(repo)[previous:] == CHAIN[1:]


def test_nondefault_xsa_has_unconditional_producer_edge(tmp_path):
    repo = checkout(tmp_path)
    result = run(repo, 'vitis:build:all', 'hardware.vivado.xsa_name=custom_xsa')
    assert result.exit_code == 0, result.output
    assert calls(repo) == CHAIN
    assert (repo / 'build/hardware/platform/custom_xsa.xsa').exists()
    metadata = json.loads((repo / 'build/software/vitis/gpgpu_platform/vitis-comp.json').read_text())
    assert metadata['hw'].endswith('/custom_xsa.xsa')
