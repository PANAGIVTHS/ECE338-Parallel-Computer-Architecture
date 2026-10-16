"""Actual Vitis task graph and portable export tests, no vendor installation."""
from pathlib import Path
from types import SimpleNamespace
import json
import os
import sys
import zipfile
import pytest
from doit.control import TaskControl
from doit.task import dict_to_task
from tools.hardware.vitis import tasks as vitis

ROOT = Path(__file__).resolve().parents[3]

class Config:
    def __init__(self, root):
        self.repo_root = root
        self.build_root = root / 'build'
        self.values = {
            'hardware.vitis.version': '2025.2',
            'hardware.vitis.platform_name': 'custom_platform',
            'hardware.vitis.host_name': 'custom_host',
            'hardware.vitis.cpu': 'ps7_cortexa9_0',
            'hardware.vitis.domain': 'standalone_ps7_cortexa9_0',
            'hardware.vitis.os': 'standalone',
            'hardware.vitis.template': 'empty_application',
            'hardware.vitis.default_archive': 'default.zip',
            'hardware.vitis.host_sources': ['src/gpgpu_driver.c', 'src/main.c'],
            'hardware.vivado.xsa_name': 'managed_hardware',
            'hardware.vivado.peripheral.base_address': '0x43C00000',
            'hardware.vivado.peripheral.range': '0x00010000',
            'tools.vitis.command': 'vitis',
        }
    def get(self, key): return self.values[key]


def make_repo(tmp_path):
    config = Config(tmp_path)
    (tmp_path / 'src').mkdir()
    for name in ('gpgpu_driver.c', 'main.c', 'gpgpu_driver.h'):
        (tmp_path / 'src' / name).write_text('/* input */')
    with zipfile.ZipFile(tmp_path / 'default.zip', 'w') as archive:
        archive.writestr('old_platform/obsolete-bsp.c', 'must not enter managed hardware')
    return config


def test_public_graph_always_rebuilds_hardware_dependency_even_if_xsa_exists(tmp_path):
    config = make_repo(tmp_path)
    xsa = config.build_root / 'hardware/platform/managed_hardware.xsa'
    xsa.parent.mkdir(parents=True); xsa.write_text('old')
    tasks = vitis.create_tasks(config)
    assert [t['name'] for t in tasks] == ['vitis:project', 'vitis:build:platform', 'vitis:build:host', 'vitis:build:all', 'vitis:export']
    assert tasks[0]['task_dep'] == ['vivado:system:build']
    assert str(xsa) in tasks[0]['file_dep']
    assert tasks[1]['task_dep'] == ['vitis:project']
    assert tasks[2]['task_dep'] == ['vitis:build:platform']
    assert tasks[3]['task_dep'] == ['vitis:build:host']
    assert not tasks[4].get('task_dep')
    assert str(tmp_path / 'src/gpgpu_driver.h') in tasks[2]['file_dep']
    assert not any('old_platform' in p for t in tasks for p in t.get('file_dep', []))
    effective = TaskControl([dict_to_task({'name': 'vivado:system:build', 'actions': [], 'targets': [str(xsa)]}), *(dict_to_task(t) for t in tasks)])
    effective.process(['vitis:build:all'])  # actual pydoit graph, including inferred file edges
    assert effective.tasks['vitis:project'].task_dep == ['vivado:system:build']
    assert 'vitis:build:host' not in effective.tasks['vitis:project'].task_dep


def test_project_and_host_use_sdk_launcher_and_real_configuration(tmp_path):
    config = make_repo(tmp_path)
    tasks = vitis.create_tasks(config)
    project = tasks[0]['actions'][0][1][0]
    host = tasks[2]['actions'][0][1][0]
    assert project[4] == 'project' and '--xsa' in project
    assert host[4] == 'host'
    assert host[host.index('--base-address') + 1] == '0x43C00000'
    assert host.count('--source') == 2
    assert tasks[0]['targets'] == [str(config.build_root / 'software/vitis/custom_platform/vitis-comp.json')]
    assert str(config.build_root / 'software/vitis/custom_host/vitis-comp.json') in tasks[2]['targets']
    assert vitis.run_vitis is tasks[0]['actions'][0][0]


def test_shipped_config_sources_headers_and_hardware_name_exist():
    from config import resolve_config
    config = resolve_config(ROOT, profile='default')
    tasks = vitis.create_tasks(config)
    assert config.get('hardware.vitis.version') == '2025.2'
    for relative in config.get('hardware.vitis.host_sources'):
        assert (ROOT / relative).is_file(), relative
    assert {Path(s).name for s in config.get('hardware.vitis.host_sources')} == {'gpgpu_driver.c', 'main.c'}
    assert tasks[0]['task_dep'] == ['vivado:system:build']
    assert str(config.build_root / 'hardware/platform/gpgpu_platform.xsa') in tasks[0]['file_dep']
    assert any(Path(s).name == 'gpgpu_driver.h' for s in tasks[2]['file_dep'])


def test_export_is_portable_atomic_deterministic_and_retains_rsa_input(tmp_path):
    workspace = tmp_path / 'workspace'
    platform = workspace / 'platform'; host = workspace / 'host'
    platform.mkdir(parents=True); (host / 'src').mkdir(parents=True)
    (platform / 'vitis-comp.json').write_text(json.dumps({'name': 'platform', 'configuration': {'xsa': str(tmp_path / 'fresh.xsa')}}))
    (host / 'vitis-comp.json').write_text(json.dumps({'name': 'host'}))
    (host / 'UserConfig.cmake').write_text(f'set(USER_COMPILE_SOURCES "{tmp_path}/src/main.c")')
    (host / 'src/app.yaml').write_text('app_src_dir: /opt/Xilinx/2025.2/Vitis/data/embeddedsw/lib/sw_apps/empty_application\n')
    rsa = platform / 'zynq_fsbl/zynq_fsbl_bsp/libsrc/xilrsa/src/librsa.a'
    rsa.parent.mkdir(parents=True); rsa.write_bytes(b'fixture vendor input')
    generated = platform / 'zynq_fsbl/zynq_fsbl_bsp/lib/libxilrsa.a'
    generated.parent.mkdir(); generated.write_bytes(b'output')
    elf = host / 'build/host.elf'; elf.parent.mkdir(); elf.write_bytes(b'output')
    archive = tmp_path / 'default.zip'
    vitis.export_workspace(workspace, archive, tmp_path, 'platform', 'host')
    with zipfile.ZipFile(archive) as result:
        names = result.namelist()
        assert 'platform/zynq_fsbl/zynq_fsbl_bsp/libsrc/xilrsa/src/librsa.a' in names
        assert not any(name.endswith('libxilrsa.a') or name.endswith('.elf') for name in names)
        assert '${GPGPU_REPO_ROOT}' in result.read('host/UserConfig.cmake').decode()
        assert '${XILINX_VITIS}' in result.read('host/src/app.yaml').decode()
        assert '${GPGPU_XSA}' in result.read('platform/vitis-comp.json').decode()
    before = archive.read_bytes(); mtime = archive.stat().st_mtime_ns
    vitis.export_workspace(workspace, archive, tmp_path, 'platform', 'host')
    assert archive.read_bytes() == before and archive.stat().st_mtime_ns == mtime
    secret = host / 'secret.txt'; secret.write_text('/home/unrelated/private')
    with pytest.raises(ValueError, match='machine-specific'):
        vitis.export_workspace(workspace, archive, tmp_path, 'platform', 'host')
    assert archive.read_bytes() == before
    secret.unlink(); secret.symlink_to(tmp_path / 'external')
    with pytest.raises(ValueError, match='symbolic link'):
        vitis.export_workspace(workspace, archive, tmp_path, 'platform', 'host')


def test_effective_graph_runs_real_entrypoint_twice_and_invalidates_inputs(tmp_path, monkeypatch):
    from doit.cmd_base import TaskLoader2
    from doit.doit_cmd import DoitMain
    config = make_repo(tmp_path)
    script = tmp_path / 'tools/hardware/vitis/vitis_flow.py'
    script.parent.mkdir(parents=True)
    script.write_bytes((ROOT / 'tools/hardware/vitis/vitis_flow.py').read_bytes())
    isolated_sdk = tmp_path / 'sdk'
    isolated_sdk.mkdir()
    (isolated_sdk / 'vitis.py').write_text('''
from pathlib import Path
import json
workspace = None

def log(event):
    with (workspace.parent / 'sdk-order.log').open('a') as out:
        out.write(event + '\\n')

class Component:
    def __init__(self, name, kind): self.name, self.kind = name, kind
    def build(self):
        log('build:' + self.name)
        root = workspace / self.name
        if self.kind == 'platform':
            out = root / 'export' / self.name
            (out / 'hw/sdt').mkdir(parents=True)
            (out / 'hw' / (self.name + '.xsa')).write_bytes((root / 'fresh-xsa').read_bytes())
            (out / 'hw/sdt/ps7_init.tcl').write_text('# fixture')
            (out / (self.name + '.xpfm')).write_text('fixture platform')
        else:
            assert 'GPGPU_BASEADDR=' in (root / 'UserConfig.cmake').read_text()
            (root / 'build').mkdir()
            (root / 'build' / (self.name + '.elf')).write_text('fixture ELF, not ARM code')
        return True

class Client:
    def set_workspace(self, path):
        global workspace
        workspace = Path(path)
    def create_platform_component(self, *, name, hw_design, os, cpu, domain_name):
        log('create:' + name)
        root = workspace / name
        root.mkdir()
        (root / 'vitis-comp.json').write_text(json.dumps({'name': name, 'kind': 'platform', 'configuration': {'xsa': hw_design}}))
        (root / 'fresh-xsa').write_bytes(Path(hw_design).read_bytes())
        return Component(name, 'platform')
    def get_component(self, *, name):
        meta = json.loads((workspace / name / 'vitis-comp.json').read_text())
        return Component(name, meta['kind'])
    def create_app_component(self, *, name, platform, domain, template):
        assert Path(platform).is_file()
        log('create:' + name)
        root = workspace / name
        (root / 'src').mkdir(parents=True)
        (root / 'vitis-comp.json').write_text(json.dumps({'name': name, 'kind': 'app'}))
        (root / 'UserConfig.cmake').write_text('set(USER_COMPILE_SOURCES)\\nset(USER_INCLUDE_DIRECTORIES)\\nset(USER_COMPILE_DEFINITIONS)\\n')
        return Component(name, 'app')

def create_client(): return Client()
''')
    launcher = tmp_path / 'fake-vitis'
    launcher.write_text(f'#!{sys.executable}\nimport subprocess, sys\nraise SystemExit(subprocess.call([sys.executable, sys.argv[2], *sys.argv[3:]]))\n')
    launcher.chmod(0o755)
    config.values['tools.vitis.command'] = str(launcher)
    monkeypatch.setenv('PYTHONPATH', str(isolated_sdk))
    hardware_input = tmp_path / 'hardware-source'; hardware_input.write_text('initial hardware')
    xsa = config.build_root / 'hardware/platform/managed_hardware.xsa'
    def hardware_build():
        xsa.parent.mkdir(parents=True, exist_ok=True)
        xsa.write_text(hardware_input.read_text())
        log = config.build_root / 'hardware-order.log'
        with log.open('a') as out: out.write('hardware\n')
    class Loader(TaskLoader2):
        def load_doit_config(self): return {'dep_file': str(tmp_path / 'doit.db'), 'verbosity': 2}
        def load_tasks(self, cmd, pos_args):
            upstream = {'name': 'vivado:system:build', 'actions': [hardware_build], 'file_dep': [str(hardware_input)], 'targets': [str(xsa)]}
            return [dict_to_task(upstream), *(dict_to_task(task) for task in vitis.create_tasks(config))]
    def run():
        assert DoitMain(Loader()).run(['run', 'vitis:build:all']) == 0
    run()
    order_log = config.build_root / 'software/sdk-order.log'
    first = order_log.read_text().splitlines()
    assert first == ['create:custom_platform', 'build:custom_platform', 'create:custom_host', 'build:custom_host']
    run()
    assert order_log.read_text().splitlines() == first
    assert (config.build_root / 'hardware-order.log').read_text().splitlines() == ['hardware']
    (tmp_path / 'src/gpgpu_driver.h').write_text('changed header')
    run()
    assert order_log.read_text().splitlines()[len(first):] == ['create:custom_host', 'build:custom_host']
    hardware_input.write_text('updated AXI hardware')
    run()
    assert order_log.read_text().splitlines()[-4:] == first
    exported = config.build_root / 'software/vitis/custom_platform/export/custom_platform/hw/custom_platform.xsa'
    assert exported.read_text() == 'updated AXI hardware'
    assert (config.build_root / 'hardware-order.log').read_text().splitlines() == ['hardware', 'hardware']


def test_missing_vendor_outputs_are_errors(tmp_path):
    with pytest.raises(FileNotFoundError, match='required artifacts'):
        vitis.run_vitis([sys.executable, '-c', 'print("vendor success")'], tmp_path, [tmp_path / 'missing.xpfm'])
