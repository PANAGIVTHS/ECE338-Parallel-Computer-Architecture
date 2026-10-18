"""2025.2 SDK contracts: deliberately isolated from vendor installations."""
from pathlib import Path
from types import ModuleType
import runpy
import sys
import pytest

ROOT = Path(__file__).resolve().parents[3]
FLOW = ROOT / 'tools/hardware/vitis/vitis_flow.py'

def sdk_module(monkeypatch, client):
    sdk = ModuleType('vitis')
    sdk.create_client = lambda: client
    monkeypatch.setitem(sys.modules, 'vitis', sdk)
    return runpy.run_path(str(FLOW))

def test_project_regenerates_hardware_through_sdk_and_keeps_backup(tmp_path, monkeypatch):
    calls = []
    xsa = tmp_path / 'fresh.xsa'
    xsa.write_text('fresh')
    old = tmp_path / 'workspace/platform'
    old.mkdir(parents=True)
    (old / 'stale-bsp.c').write_text('2026 BSP')
    class Client:
        def set_workspace(self, path):
            calls.append(('workspace', path))
        def create_platform_component(self, *, name, hw_design, os, cpu, domain_name):
            calls.append(('create', name, hw_design, os, cpu, domain_name))
            old.mkdir()
            (old / 'vitis-comp.json').write_text('{}')
            return self
    module = sdk_module(monkeypatch, Client())
    module['create_project'](old.parent, xsa, 'platform', 'ps7_cortexa9_0', 'standalone', 'standalone_ps7_cortexa9_0')
    assert calls[-1] == ('create', 'platform', str(xsa.resolve()), 'standalone', 'ps7_cortexa9_0', 'standalone_ps7_cortexa9_0')
    assert not (old / 'stale-bsp.c').exists()
    assert list(tmp_path.rglob('stale-bsp.c'))  # preserve user state outside live component

def test_failed_sdk_creation_restores_previous_component(tmp_path, monkeypatch):
    xsa = tmp_path / 'fresh.xsa'; xsa.write_text('fresh')
    old = tmp_path / 'ws/platform'; old.mkdir(parents=True)
    (old / 'user-edit').write_text('saved')
    class Client:
        def set_workspace(self, path): pass
        def create_platform_component(self, **kwargs):
            old.mkdir(); (old / 'partial').write_text('failed')
            raise RuntimeError('SDK rejected XSA')
    module = sdk_module(monkeypatch, Client())
    with pytest.raises(RuntimeError, match='rejected XSA'):
        module['create_project'](old.parent, xsa, 'platform', 'cpu', 'standalone', 'domain')
    assert (old / 'user-edit').read_text() == 'saved'
    assert not (old / 'partial').exists()

def test_actual_user_config_sources_includes_and_base_preserve_other_defines(tmp_path, monkeypatch):
    module = sdk_module(monkeypatch, object())
    root = tmp_path / 'host'; root.mkdir()
    config = root / 'UserConfig.cmake'
    config.write_text('set(USER_COMPILE_SOURCES "old.c")\nset(USER_INCLUDE_DIRECTORIES)\nset(USER_COMPILE_DEFINITIONS "KEEP=1" "GPGPU_BASEADDR=0x41200000")\n')
    sources = [tmp_path / 'sources/gpgpu_driver.c', tmp_path / 'sources/main.c']
    module['configure_host'](root, sources, '0x43C00000')
    text = config.read_text()
    assert all(str(source.resolve()) in text for source in sources)
    assert str(sources[0].parent.resolve()) in text
    assert 'GPGPU_BASEADDR=0x43C00000' in text
    assert '0x41200000' not in text
    assert 'KEEP=1' in text
    before = config.stat().st_mtime_ns
    module['configure_host'](root, sources, '0x43C00000')
    assert config.stat().st_mtime_ns == before

def test_real_cmake_consumes_correct_sources_include_and_base(tmp_path, monkeypatch):
    import subprocess
    module = sdk_module(monkeypatch, object())
    sources_dir = tmp_path / 'checkout with spaces/sources'
    sources_dir.mkdir(parents=True)
    driver = sources_dir / 'gpgpu_driver.c'
    driver.write_text('#include "gpgpu_driver.h"\nunsigned base(void) { return GPGPU_BASEADDR; }\n')
    main = sources_dir / 'main.c'
    main.write_text('#include "gpgpu_driver.h"\nint main(void) { return base() != 0x43C10000; }\n')
    (sources_dir / 'gpgpu_driver.h').write_text('unsigned base(void);\n')
    host = tmp_path / 'app'; host.mkdir()
    (host / 'UserConfig.cmake').write_text('set(USER_COMPILE_SOURCES)\nset(USER_INCLUDE_DIRECTORIES)\nset(USER_COMPILE_DEFINITIONS "KEEP=1")\n')
    module['configure_host'](host, [driver, main], '0x43C10000')
    (host / 'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.16)\nproject(host C)\ninclude(UserConfig.cmake)\nadd_executable(host ${USER_COMPILE_SOURCES})\ntarget_include_directories(host PRIVATE ${USER_INCLUDE_DIRECTORIES})\ntarget_compile_definitions(host PRIVATE ${USER_COMPILE_DEFINITIONS})\n')
    subprocess.run(['cmake', '-S', str(host), '-B', str(host / 'build')], check=True, capture_output=True)
    subprocess.run(['cmake', '--build', str(host / 'build')], check=True, capture_output=True)
    subprocess.run([str(host / 'build/host')], check=True)


@pytest.mark.parametrize('separator', [False, True])
def test_host_entrypoint_creates_sdk_app_after_platform_and_imports_only_editable_archive(tmp_path, monkeypatch, separator):
    import json
    import zipfile
    workspace = tmp_path / 'workspace'
    xpfm = workspace / 'platform/export/platform/platform.xpfm'
    xpfm.parent.mkdir(parents=True); xpfm.write_text('SDK fixture')
    sources = [tmp_path / 'gpgpu_driver.c', tmp_path / 'main.c']
    for path in sources: path.write_text('/* configured source */')
    archive = tmp_path / 'export.zip'
    with zipfile.ZipFile(archive, 'w') as output:
        output.writestr('platform/bsp/stale.c', 'stale SDK source')
        output.writestr('host/src/custom.c', '/* editable */')
        output.writestr('host/src/UserConfig.cmake', 'set(USER_COMPILE_SOURCES "old.c")\nset(USER_INCLUDE_DIRECTORIES "${GPGPU_REPO_ROOT}/include")\nset(USER_COMPILE_DEFINITIONS "KEEP=1")\nset(USER_LINKER_SCRIPT "old-memory-map.ld")\n# OLD SDK GENERATED LOGIC\n')
        output.writestr('host/src/lscript.ld', 'stale hardware map')
    calls = []
    class Client:
        def set_workspace(self, path): calls.append(('workspace', path))
        def create_app_component(self, *, name, platform, domain, template):
            assert platform == str(xpfm.resolve()) and name == 'host'
            calls.append(('create', domain, template))
            root = workspace / 'host'
            (root / 'src').mkdir(parents=True)
            (root / 'vitis-comp.json').write_text(json.dumps({'name': 'host'}))
            (root / 'UserConfig.cmake').write_text('set(USER_COMPILE_SOURCES)\nset(USER_INCLUDE_DIRECTORIES)\nset(USER_COMPILE_DEFINITIONS)\nset(USER_LINKER_SCRIPT "${CMAKE_SOURCE_DIR}/src/lscript.ld")\n# FRESH SDK GENERATED LOGIC\n')
            (root / 'src/lscript.ld').write_text('fresh SDK memory map')
            return self
        def build(self):
            config = (workspace / 'host/UserConfig.cmake').read_text()
            assert 'GPGPU_BASEADDR=0x43C00000' in config
            assert all(str(p) in config for p in sources)
            assert '${GPGPU_REPO_ROOT}' not in config
            assert (workspace / 'host/src/custom.c').read_text() == '/* editable */'
            assert (workspace / 'host/src/lscript.ld').read_text() == 'fresh SDK memory map'
            assert not (workspace / 'platform/bsp/stale.c').exists()
            calls.append(('build',))
            return True
    sdk_module(monkeypatch, Client())
    argv = [str(FLOW)] + (['--'] if separator else []) + ['host', '--workspace', str(workspace), '--component', 'host', '--platform', 'platform', '--domain', 'domain', '--template', 'empty_application', '--base-address', '0x43C00000', '--archive', str(archive), '--repo-root', str(tmp_path)]
    for path in sources: argv += ['--source', str(path)]
    monkeypatch.setattr(sys, 'argv', argv)
    runpy.run_path(str(FLOW), run_name='__main__')
    assert calls == [('workspace', str(workspace.resolve())), ('create', 'domain', 'empty_application'), ('build',)]


def test_missing_xsa_never_launches_sdk(tmp_path, monkeypatch):
    module = sdk_module(monkeypatch, object())
    with pytest.raises(FileNotFoundError):
        module['create_project'](tmp_path / 'ws', tmp_path / 'missing.xsa', 'platform', 'cpu', 'standalone', 'domain')
    assert not (tmp_path / 'ws').exists()
