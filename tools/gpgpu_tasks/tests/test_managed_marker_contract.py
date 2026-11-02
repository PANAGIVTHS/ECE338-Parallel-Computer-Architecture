"""Managed marker ownership checks are read-only and never invoke vendors."""
import json

import pytest

from tools.hardware.vivado import tasks

NAME = 'gpgpu_system'
PART = 'xc7z020clg484-1'


@pytest.fixture(autouse=True)
def no_vendor_calls(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Marker checks must not invoke a vendor')
    monkeypatch.setattr(tasks.subprocess, 'run', forbidden)
    monkeypatch.setattr(tasks.subprocess, 'Popen', forbidden)


def test_prepare_generated_marker_is_accepted_by_saved_current(tmp_path):
    directory = tmp_path / NAME
    tasks.prepare_managed_project(directory, NAME, PART, 'system')
    marker = directory / '.gpgpu-managed.json'
    before = marker.read_bytes()
    assert json.loads(before) == {
        'project': NAME, 'part': PART, 'kind': 'system', 'schema': 1,
    }
    assert tasks.saved_current(directory, NAME, PART, directory / 'design_1.bd') is True
    assert marker.read_bytes() == before


def tree_state(root):
    return {
        path.relative_to(root).as_posix(): (
            ('symlink', str(path.readlink())) if path.is_symlink()
            else ('file', path.read_bytes()) if path.is_file()
            else ('directory',)
        ) for path in root.rglob('*')
    }


def check_state(directory, operation):
    if operation == 'saved':
        return tasks.saved_current(directory, NAME, PART, directory / 'design_1.bd')
    return tasks.prepare_managed_project(
        directory, NAME, PART, 'system', recreate=operation == 'recreate',
    )


@pytest.mark.parametrize('operation', ['prepare', 'recreate', 'saved'])
@pytest.mark.parametrize('contents', [
    '{invalid', 'null', '[]', '1', '"marker"',
    *[json.dumps({key: value for key, value in {
        'project': NAME, 'part': PART, 'kind': 'system', 'schema': 1,
    }.items() if key != missing}) for missing in ('project', 'part', 'kind', 'schema')],
    *[json.dumps(dict(project=NAME, part=PART, kind='system', schema=1, **extra))
      for extra in ({'name': NAME},)],
    *[json.dumps({**{'project': NAME, 'part': PART, 'kind': 'system', 'schema': 1},
                  key: value})
      for key, value in [('project', 'foreign'), ('part', 'wrong-part'), ('kind', 'ip'),
                         ('schema', 2), ('schema', True), ('schema', 1.0), ('schema', '1')]],
    json.dumps({'name': NAME, 'part': PART, 'kind': 'system'}),
])
def test_invalid_marker_is_rejected_without_mutation(tmp_path, operation, contents):
    directory = tmp_path / NAME
    directory.mkdir()
    (directory / '.gpgpu-managed.json').write_text(contents)
    before = tree_state(tmp_path)
    with pytest.raises(RuntimeError):
        check_state(directory, operation)
    assert tree_state(tmp_path) == before


@pytest.mark.parametrize('operation', ['prepare', 'recreate', 'saved'])
@pytest.mark.parametrize('populated', [False, True])
def test_missing_marker_is_rejected_even_in_empty_directory(tmp_path, operation, populated):
    directory = tmp_path / NAME
    directory.mkdir()
    if populated:
        (directory / 'foreign.xpr').write_text('preserve foreign project')
    before = tree_state(tmp_path)
    with pytest.raises(RuntimeError):
        check_state(directory, operation)
    assert tree_state(tmp_path) == before


@pytest.mark.parametrize('operation', ['prepare', 'recreate', 'saved'])
@pytest.mark.parametrize('target_exists', [False, True])
def test_symlink_marker_is_rejected_without_following_or_mutating_it(tmp_path, operation, target_exists):
    directory = tmp_path / NAME
    directory.mkdir()
    target = tmp_path / 'external-marker.json'
    if target_exists:
        target.write_text(json.dumps({
            'project': NAME, 'part': PART, 'kind': 'system', 'schema': 1,
        }))
    (directory / '.gpgpu-managed.json').symlink_to(target)
    before = tree_state(tmp_path)
    with pytest.raises(RuntimeError):
        check_state(directory, operation)
    assert tree_state(tmp_path) == before


@pytest.mark.parametrize('operation', ['prepare', 'recreate', 'saved'])
@pytest.mark.parametrize('target_exists', [False, True])
def test_symlink_project_remains_rejected(tmp_path, operation, target_exists):
    target = tmp_path / 'external-project'
    if target_exists:
        tasks.prepare_managed_project(target, NAME, PART, 'system')
    directory = tmp_path / NAME
    directory.symlink_to(target, target_is_directory=True)
    before = tree_state(tmp_path)
    with pytest.raises(RuntimeError):
        check_state(directory, operation)
    assert tree_state(tmp_path) == before


def bd_payload():
    return {'design': {
        'design_info': {'name': 'design_1', 'device': PART},
        'components': {'processing_system7_0': {}, 'gpgpu_ctrl': {},
                       'gpgpu_axi_0': {'vlnv': 'user.org:user:gpgpu_axi:1.0'}},
    }}


def test_generated_marker_and_compatible_saved_bd_are_accepted_read_only(tmp_path):
    directory = tmp_path / NAME
    tasks.prepare_managed_project(directory, NAME, PART, 'system')
    (directory / 'design_1.bd').write_text(json.dumps(bd_payload()))
    before = tree_state(tmp_path)
    assert check_state(directory, 'saved') is True
    check_state(directory, 'prepare')
    assert tree_state(tmp_path) == before


@pytest.mark.parametrize('conflict', ['name', 'part', 'vlnv', 'gpio', 'missing_ps', 'invalid_json'])
def test_valid_marker_does_not_relax_saved_bd_guards(tmp_path, conflict):
    directory = tmp_path / NAME
    tasks.prepare_managed_project(directory, NAME, PART, 'system')
    payload = bd_payload()
    design = payload['design']
    if conflict == 'name':
        design['design_info']['name'] = 'foreign'
    elif conflict == 'part':
        design['design_info']['device'] = 'foreign'
    elif conflict == 'vlnv':
        design['components']['gpgpu_axi_0']['vlnv'] = 'foreign:user:ip:1.0'
    elif conflict == 'gpio':
        design['components']['axi_gpio_0'] = {}
    elif conflict == 'missing_ps':
        del design['components']['processing_system7_0']
    (directory / 'design_1.bd').write_text(
        '{invalid' if conflict == 'invalid_json' else json.dumps(payload),
    )
    before = tree_state(tmp_path)
    with pytest.raises(RuntimeError):
        check_state(directory, 'saved')
    assert tree_state(tmp_path) == before


def test_absent_project_saved_check_is_read_only(tmp_path):
    directory = tmp_path / NAME
    assert check_state(directory, 'saved') is True
    assert not directory.exists()
