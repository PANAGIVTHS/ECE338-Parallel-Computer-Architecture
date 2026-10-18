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
