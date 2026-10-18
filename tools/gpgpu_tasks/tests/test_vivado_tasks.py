"""Staged Vivado ownership and portable command contracts (production config)."""
from pathlib import Path

import pytest
from config import resolve_config
from tools.hardware.vivado.tasks import create_tasks

ROOT = Path(__file__).resolve().parents[3]


def graph(tmp_path, *values):
    config = resolve_config(ROOT, overrides=[f'paths.build.root={tmp_path / "output"}', *values])
    return {task['name']: task for task in create_tasks(config)}


def test_standalone_public_tasks_and_system_checkpoint_chain(tmp_path):
    tasks = graph(tmp_path)
    chain = ['vivado:ip:create', 'vivado:ip:build', 'vivado:system:create',
             'vivado:system:_synthesis', 'vivado:system:_implementation',
             'vivado:system:_bitstream', 'vivado:system:build']
    assert set(tasks) == set(chain)
    for first, second in zip(chain, chain[1:]):
        assert tasks[second]['task_dep'] == [first]
    assert tasks[chain[0]]['task_dep'] == []


def test_configured_vendor_and_arguments_in_all_commands(tmp_path):
    tasks = graph(tmp_path, 'tools.vivado.command=custom-vivado', 'architecture.num_cores=4', 'hardware.vivado.jobs=2')
    for task in tasks.values():
        command = task['actions'][0][1][0]
        assert command[0] == 'custom-vivado'
        assert command[command.index('-num-cores') + 1] == '4'
        assert command[command.index('-jobs') + 1] == '2'
        assert command[command.index('-rtl-dir') + 1] == str(ROOT / 'hardware/rtl/gpgpu')
        assert command[command.index('-version') + 1] == '2025.2'
        assert Path(command[command.index('-source') + 1]).is_file()
        assert str(tmp_path / 'output') in command[command.index('-project-dir') + 1]
        assert not any('/GPU/' in dep for dep in task['file_dep'])


def test_shared_xsa_identity(tmp_path):
    tasks = graph(tmp_path, 'hardware.vivado.xsa_name=custom_platform')
    assert tasks['vivado:system:build']['targets'] == [str(tmp_path / 'output/hardware/platform/custom_platform.xsa')]
    assert tasks['vivado:system:_bitstream']['targets'] == [str(tmp_path / 'output/hardware/bitstream/design_1_wrapper.bit')]


@pytest.mark.parametrize('value', ['"41200000"', '"0xnothex"', '"0x43C00001"', '"0x100000000"', '1092616192'])
def test_peripheral_address_validation_rejects_invalid_values(tmp_path, value):
    with pytest.raises(ValueError):
        graph(tmp_path, f'hardware.vivado.peripheral.base_address={value}')


def test_discovery_has_no_vendor_execution_or_build_mutation(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Vendor invoked during discovery')
    monkeypatch.setattr('subprocess.run', forbidden)
    monkeypatch.setattr('subprocess.Popen', forbidden)
    graph(tmp_path)
    assert not (tmp_path / 'output').exists()
