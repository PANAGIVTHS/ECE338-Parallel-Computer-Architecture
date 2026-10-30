from pathlib import Path

import pytest
from config import resolve_config
from tools.hardware.vivado import tasks

ROOT = Path(__file__).resolve().parents[3]


def config(tmp_path, *overrides):
    return resolve_config(repo_root=ROOT, overrides=[f'paths.build.root={tmp_path / "fresh"}', *overrides])


def test_shipped_config_and_public_graph(tmp_path):
    cfg = config(tmp_path)
    graph = {t['name']: t for t in tasks.create_tasks(cfg)}
    assert {'vivado:ip:create', 'vivado:ip:build', 'vivado:system:create', 'vivado:system:build'} <= graph.keys()
    assert 'vivado:project' not in graph
    assert 'vivado:xsa' not in graph
    assert graph['vivado:ip:build']['task_dep'] == ['vivado:ip:create']
    assert graph['vivado:system:create']['task_dep'] == ['vivado:ip:build']
    assert cfg.get('hardware.vivado.project_name') == 'gpgpu_system'
    assert cfg.get('hardware.vivado.version') == '2025.2'


def test_production_discovery_includes_headers_control_interfaces(tmp_path):
    cfg = config(tmp_path)
    graph = {t['name']: t for t in tasks.create_tasks(cfg)}
    deps = graph['vivado:ip:create']['file_dep']
    for file in ('constants.svh', 'control/MMIOController.sv', 'interfaces/AXI4LiteTop.v', 'memory/MemoryInterface.sv'):
        assert str(ROOT / 'hardware/rtl/gpgpu' / file) in deps
    assert not any('experimental' in f for f in deps)
    assert not any(f.endswith('.xdc') for f in deps)


def test_protected_project_is_rejected_without_any_vendor_call(tmp_path):
    project = tmp_path / 'gpgpu_ip_dev'
    project.mkdir()
    source = project / 'gpgpu_ip_dev.xpr'
    source.write_text('reference')
    with pytest.raises(RuntimeError, match='unmanaged|protected'):
        tasks.prepare_managed_project(project, 'gpgpu_ip_dev', 'xc7z020clg484-1', 'ip', recreate=True)
    assert source.read_text() == 'reference'


def test_managed_recreation_retains_complete_snapshot(tmp_path):
    directory = tmp_path / 'dev'
    tasks.prepare_managed_project(directory, 'dev', 'part', 'ip')
    (directory / 'gui-state.txt').write_text('keep')
    tasks.prepare_managed_project(directory, 'dev', 'part', 'ip', recreate=True)
    snapshots = list((tmp_path / '.snapshots').iterdir())
    assert len(snapshots) == 1
    assert (snapshots[0] / 'gui-state.txt').read_text() == 'keep'
    assert not (directory / 'gui-state.txt').exists()


def test_configuration_invalidates_every_downstream_stage(tmp_path):
    first = {t['name']: t for t in tasks.create_tasks(config(tmp_path))}
    for override in ('architecture.num_cores=4', 'hardware.vivado.peripheral.base_address="0x44000000"'):
        changed = {t['name']: t for t in tasks.create_tasks(config(tmp_path, override))}
        for name in first:
            assert changed[name]['uptodate'][0].config != first[name]['uptodate'][0].config


def test_unique_producer_ownership_and_stage_inputs(tmp_path):
    graph = tasks.create_tasks(config(tmp_path))
    targets = [target for task in graph for target in task['targets']]
    assert len(targets) == len(set(targets))
    synthesis = next(t for t in graph if t['name'] == 'vivado:system:_synthesis')
    assert any(f.endswith('design_1.bd') for f in synthesis['file_dep'])
    assert any(f.endswith('smart_zynq.xdc') for f in synthesis['file_dep'])
    assert any(f.endswith('.gpgpu-package.json') for f in synthesis['file_dep'])


@pytest.mark.parametrize('override', [
    'hardware.vivado.peripheral.base_address=0x43C00001',
    'hardware.vivado.peripheral.range=0x100000',
    'hardware.vivado.top=bad_wrapper',
    'hardware.vivado.xsa_name=../escape',
])
def test_invalid_contract_rejected_before_execution(tmp_path, override):
    with pytest.raises(ValueError):
        tasks.create_tasks(config(tmp_path, override))


def test_portable_export_rejects_legacy_and_normalizes_config(tmp_path):
    text = '''# user.org:user:gpgpu_axi:1.0
set design_name design_1
set_property CONFIG.SP_PER_SM {32} [get_bd_cells gpgpu_axi_0]
set_property -dict [list CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ {35} CONFIG.PCW_USE_M_AXI_GP0 {1}] $processing_system7_0
assign_bd_address -offset 0x43C00000 -range 0x00010000 -target_address_space [get_bd_addr_spaces processing_system7_0/Data] [get_bd_addr_segs gpgpu_axi_0/s00_axi/reg0] -force
'''
    result = tasks.normalize_exported_tcl(text, ROOT, 'design_1')
    assert '$::NUM_CORES' in result and '$::AXI_BASE' in result and '$::AXI_RANGE' in result
    assert 'CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ $::FCLK0_MHZ' in result and '{35}' not in result
    assert result == tasks.normalize_exported_tcl(result, ROOT, 'design_1')
    for invalid in ('set design_name design_1\n# axi_gpio', text + '\n# /home/user/path', text + '\n# C:\\Users\\foo'):
        with pytest.raises(RuntimeError):
            tasks.normalize_exported_tcl(invalid, ROOT, 'design_1')


def test_package_publication_manifest_detects_partial_or_tampered_cache(tmp_path):
    from config import resolve_config
    inputs = tasks.production_inputs(resolve_config(ROOT))
    assert tasks.package_current(tmp_path, ROOT, inputs) is False
    data = tmp_path / 'src.sv'; data.write_text('one')
    (tmp_path / '.gpgpu-package.json').write_text(__import__('json').dumps({
        'revision': 1, 'files': tasks._tree_hash(tmp_path)}))
    assert tasks.package_current(tmp_path, ROOT, inputs) is False  # Hash alone isn't IP-XACT proof.


def test_generated_ip_callback_tracks_content_after_first_creation(tmp_path):
    callback = tasks.GeneratedIPChanged(tmp_path)
    state = type('Task', (), {'value_savers': []})()
    callback.configure_task(state)
    source = tmp_path / 'bd/ip/core.xci'; source.parent.mkdir(parents=True)
    source.write_text('one')
    saved = state.value_savers[0]()
    assert callback(None, saved) is True
    source.write_text('two')
    assert callback(None, saved) is False
