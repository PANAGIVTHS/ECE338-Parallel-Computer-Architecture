"""Saved design preservation and stage failure tests; all state is disposable."""
import json
from pathlib import Path
import zipfile

import pytest
from tools.hardware.vivado import tasks

def payload(name='design_1', part='xc7z020clg484-1'):
    return {'design': {'design_info': {'name': name, 'device': part},
                       'components': {'processing_system7_0': {}, 'axi_smc': {},
                                      'gpgpu_axi_0': {'vlnv': 'user.org:user:gpgpu_axi:1.0'}},
                       'gui_property': 'preserve me'}}


def test_valid_saved_bd_validation_is_read_only(tmp_path):
    bd = tmp_path / 'design_1.bd'
    bd.write_text(json.dumps(payload()))
    before = bd.read_bytes()
    tasks.validate_saved_bd(bd, 'design_1', 'xc7z020clg484-1')
    assert bd.read_bytes() == before


@pytest.mark.parametrize('kind', ['name', 'part', 'vlnv', 'gpio', 'missing_ps', 'invalid_json'])
def test_incompatible_saved_bd_fails_without_mutation(tmp_path, kind):
    data = payload()
    if kind in ('name', 'part'):
        data = payload(name='other' if kind == 'name' else 'design_1', part='wrong' if kind == 'part' else 'xc7z020clg484-1')
    elif kind == 'vlnv': data['design']['components']['gpgpu_axi_0']['vlnv'] = 'other:user:ip:1.0'
    elif kind == 'gpio': data['design']['components']['axi_gpio_cmd'] = {}
    elif kind == 'missing_ps': del data['design']['components']['processing_system7_0']
    bd = tmp_path / 'design_1.bd'
    bd.write_text('{invalid' if kind == 'invalid_json' else json.dumps(data))
    before = bd.read_bytes()
    with pytest.raises(RuntimeError): tasks.validate_saved_bd(bd, 'design_1', 'xc7z020clg484-1')
    assert bd.read_bytes() == before


def test_incompatible_managed_identity_is_not_adopted(tmp_path):
    directory = tmp_path / 'project'
    tasks.prepare_managed_project(directory, 'original', 'part', 'system')
    before = (directory / '.gpgpu-managed.json').read_bytes()
    with pytest.raises(RuntimeError, match='identity'):
        tasks.prepare_managed_project(directory, 'different', 'part', 'system')
    assert (directory / '.gpgpu-managed.json').read_bytes() == before


@pytest.mark.parametrize('missing', [None, 'bit', 'hwh', 'tcl', 'c'])
def test_xsa_checks_bitstream_handoff_and_ps_init(tmp_path, monkeypatch, missing):
    target = tmp_path / 'platform.xsa'
    with zipfile.ZipFile(target, 'w') as archive:
        for kind, name in [('bit','design.bit'), ('hwh','design.hwh'), ('tcl','ps7_init.tcl'), ('c','ps7_init.c')]:
            if kind != missing: archive.writestr(name, 'test fixture, not hardware output')
    monkeypatch.setattr(tasks, 'run_vivado', lambda *args: None)
    if missing:
        with pytest.raises(RuntimeError, match='XSA lacks'):
            tasks.run_stage([], tmp_path, tmp_path, target, True)
    else: tasks.run_stage([], tmp_path, tmp_path, target, True)


def test_stage_rejects_success_without_promised_output(tmp_path, monkeypatch):
    monkeypatch.setattr(tasks, 'run_vivado', lambda *args: None)
    with pytest.raises(RuntimeError, match='did not produce'):
        tasks.run_stage([], tmp_path, tmp_path, tmp_path / 'missing.dcp')


def fake_runs(project):
    """Run directories as launch_runs leaves them (contents are fixtures)."""
    runs = project / 'gpgpu_system.runs'
    files = {
        'synth_1': ['runme.log', 'design_1_wrapper.vds', 'design_1_wrapper_utilization_synth.rpt',
                    'design_1_wrapper.dcp', 'runme.sh'],
        'design_1_gpgpu_axi_0_0_synth_1': ['runme.log', 'design_1_gpgpu_axi_0_0.vds'],
        'design_1_processing_system7_0_0_synth_1': ['runme.log', 'design_1_processing_system7_0_0.vds'],
        'impl_1': ['runme.log', 'design_1_wrapper.vdi', 'design_1_wrapper_timing_summary_routed.rpt',
                   'design_1_wrapper_routed.dcp'],
    }
    for run, names in files.items():
        (runs / run).mkdir(parents=True)
        for name in names:
            (runs / run / name).write_text(f'{run}/{name}')
    return files


SYNTH = ['-source', 'tools/hardware/vivado/synthesis.tcl']


def test_stage_collects_every_synthesis_run_log(tmp_path, monkeypatch):
    fake_runs(tmp_path)
    target = tmp_path / 'design_1_wrapper.dcp'
    target.write_text('checkpoint')
    monkeypatch.setattr(tasks, 'run_vivado', lambda *args: None)
    tasks.run_stage(SYNTH, tmp_path, tmp_path, target, runs=['*synth_1'])
    logs = tmp_path / '.gpgpu/logs/synthesis'
    collected = sorted(p.relative_to(logs).as_posix() for p in logs.rglob('*') if p.is_file())
    assert collected == [
        'design_1_gpgpu_axi_0_0_synth_1/design_1_gpgpu_axi_0_0.vds',
        'design_1_gpgpu_axi_0_0_synth_1/runme.log',
        'design_1_processing_system7_0_0_synth_1/design_1_processing_system7_0_0.vds',
        'design_1_processing_system7_0_0_synth_1/runme.log',
        'synth_1/design_1_wrapper.vds',
        'synth_1/design_1_wrapper_utilization_synth.rpt',
        'synth_1/runme.log',
    ]
    assert (logs / 'synth_1/runme.log').read_text() == 'synth_1/runme.log'


def test_stage_collects_run_logs_when_vivado_fails(tmp_path, monkeypatch):
    fake_runs(tmp_path)
    stale = tmp_path / '.gpgpu/logs/implementation/old_run/runme.log'
    stale.parent.mkdir(parents=True)
    stale.write_text('previous build')

    def failing(*args):
        raise RuntimeError('Vivado stage implementation failed')
    monkeypatch.setattr(tasks, 'run_vivado', failing)
    with pytest.raises(RuntimeError, match='failed'):
        tasks.run_stage(['-source', 'implementation.tcl'], tmp_path, tmp_path, tmp_path / 'routed.dcp',
                        runs=['impl_1'])
    logs = tmp_path / '.gpgpu/logs/implementation'
    assert not stale.exists()
    assert sorted(p.name for p in (logs / 'impl_1').iterdir()) == [
        'design_1_wrapper.vdi', 'design_1_wrapper_timing_summary_routed.rpt', 'runme.log']
    assert [p.name for p in logs.iterdir()] == ['impl_1']


def test_system_build_stages_collect_their_runs(tmp_path):
    from config import resolve_config
    root = Path(__file__).resolve().parents[3]
    config = resolve_config(root, overrides=[f'paths.build.root={tmp_path / "output"}'])
    graph = {t['name']: t for t in tasks.create_tasks(config)}
    runs = {name: graph[name]['actions'][0][2].get('runs') for name in graph}
    assert runs['vivado:system:_synthesis'] == ['*synth_1']
    assert runs['vivado:system:_implementation'] == ['impl_1']
    assert runs['vivado:system:_bitstream'] == ['impl_1']
    assert runs['vivado:ip:create'] is None and runs['vivado:system:build'] is None
