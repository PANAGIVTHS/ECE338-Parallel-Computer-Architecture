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
        # Source lists travel in a file: list-valued -tclargs get mangled by Vivado.
        assert command[command.index('-sources-manifest') + 1] == str(
            tmp_path / 'output/hardware/vivado/gpgpu_ip_dev/.gpgpu/sources.tsv')
        assert not any('{' in arg or len(arg) > 1024 for arg in command)
        assert command[command.index('-flow-version') + 1] == '2025.2'
        assert command[command.index('-fclk0-mhz') + 1] == '35'
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


def test_vivado_argv_parses_and_manifest_round_trips_through_tcl(tmp_path):
    """Feed common.tcl the exact -tclargs the flow builds, then read the manifest."""
    import tkinter
    from tools.hardware.vivado import tasks as vivado
    flow = ROOT / 'tools/hardware/vivado'
    config = resolve_config(ROOT, overrides=[f'paths.build.root={tmp_path / "output"}'])
    command = {t['name']: t for t in create_tasks(config)}['vivado:ip:create']['actions'][0][1][0]
    inputs = vivado.production_inputs(config)
    manifest = command[command.index('-sources-manifest') + 1]
    vivado.write_source_manifest(manifest, inputs)
    tcl = tkinter.Tcl()
    tcl.createcommand('version', lambda *args: command[command.index('-flow-version') + 1])
    tcl.call('set', 'argv', tuple(command[command.index('-tclargs') + 1:]))
    tcl.eval(f'source {{{flow / "common.tcl"}}}')
    tcl.eval(f'source {{{flow / "production_sources.tcl"}}}')
    memory, sources, headers = tcl.splitlist(tcl.eval('read_source_manifest $SOURCES_MANIFEST'))
    assert Path(memory) == inputs[0]
    assert [Path(p) for p in tcl.splitlist(sources)] == inputs[1]
    assert [Path(p) for p in tcl.splitlist(headers)] == inputs[2]


def test_source_manifest_keeps_awkward_paths_intact(tmp_path):
    import tkinter
    from tools.hardware.vivado import tasks as vivado
    odd = tmp_path / 'dir with {braces} and spaces'
    odd.mkdir()
    files = [odd / name for name in ('init.mem', 'a b.svh', 'x{y}.sv')]
    for f in files:
        f.write_text('')
    manifest = tmp_path / 'sources.tsv'
    vivado.write_source_manifest(manifest, (files[0], files[1:], [files[1]]))
    tcl = tkinter.Tcl()
    tcl.eval(f'source {{{ROOT / "tools/hardware/vivado/production_sources.tcl"}}}')
    tcl.call('set', 'manifest', str(manifest))
    tcl.eval('lassign [read_source_manifest $manifest] m s h')
    assert tcl.eval('set m') == str(files[0])
    assert [Path(p) for p in tcl.splitlist(tcl.eval('production_source_paths $m $s $h'))] == files
    with pytest.raises(ValueError):
        vivado.write_source_manifest(manifest, (files[0], [tmp_path / 'bad\tname.sv'], []))


@pytest.mark.parametrize('value,expected', [('50', '50'), ('62.5', '62.5'), ('100.0', '100')])
def test_fabric_clock_reaches_every_vivado_stage(tmp_path, value, expected):
    tasks = graph(tmp_path, f'hardware.vivado.fabric_clock_mhz={value}')
    for task in tasks.values():
        command = task['actions'][0][1][0]
        assert command[command.index('-fclk0-mhz') + 1] == expected


@pytest.mark.parametrize('value', ['0', '-35', 'true', '"35"'])
def test_fabric_clock_must_be_a_positive_number(tmp_path, value):
    with pytest.raises(ValueError, match='fabric_clock_mhz'):
        graph(tmp_path, f'hardware.vivado.fabric_clock_mhz={value}')


@pytest.mark.parametrize('value,expected', [('true', '1'), ('false', '0')])
def test_post_route_phys_opt_reaches_every_vivado_stage(tmp_path, value, expected):
    tasks = graph(tmp_path, f'hardware.vivado.post_route_phys_opt.enabled={value}',
                  'hardware.vivado.post_route_phys_opt.directive=Explore')
    for task in tasks.values():
        command = task['actions'][0][1][0]
        assert command[command.index('-post-route-phys-opt') + 1] == expected
        assert command[command.index('-post-route-phys-opt-directive') + 1] == 'Explore'


@pytest.mark.parametrize('key,value', [
    ('enabled', '1'), ('enabled', '"true"'), ('enabled', 'null'),
    ('directive', '""'), ('directive', '"Aggressive Explore"'), ('directive', '"x;exit"'), ('directive', 'null'),
])
def test_post_route_phys_opt_rejects_invalid_values(tmp_path, key, value):
    with pytest.raises(ValueError, match=f'post_route_phys_opt.{key}'):
        graph(tmp_path, f'hardware.vivado.post_route_phys_opt.{key}={value}')


def test_shipped_profile_runs_aggressive_post_route_phys_opt():
    config = resolve_config(ROOT)
    assert config.get('hardware.vivado.post_route_phys_opt.enabled') is True
    assert config.get('hardware.vivado.post_route_phys_opt.directive') == 'AggressiveExplore'


@pytest.mark.parametrize('enabled', [True, False])
def test_implementation_applies_post_route_phys_opt(tmp_path, enabled):
    """Run implementation.tcl against recorded Vivado commands."""
    import tkinter
    flow = ROOT / 'tools/hardware/vivado'
    config = resolve_config(ROOT, overrides=[f'paths.build.root={tmp_path / "output"}',
                                             f'hardware.vivado.post_route_phys_opt.enabled={str(enabled).lower()}',
                                             'hardware.vivado.post_route_phys_opt.directive=AggressiveExplore'])
    command = {t['name']: t for t in create_tasks(config)}['vivado:system:_implementation']['actions'][0][1][0]
    argv = command[command.index('-tclargs') + 1:]
    run_dir = Path(argv[argv.index('-project-dir') + 1]) / f"{argv[argv.index('-project-name') + 1]}.runs/impl_1"
    top = argv[argv.index('-top') + 1]
    calls = []
    properties = {}

    def record(name):
        def call(*args):
            calls.append((name, *args))
            if name == 'set_property':
                properties[args[0]] = args[1]
            if name == 'launch_runs':
                # Vivado runs every enabled step before write_bitstream
                run_dir.mkdir(parents=True, exist_ok=True)
                (run_dir / f'{top}_routed.dcp').write_text('')
                if properties.get('STEPS.POST_ROUTE_PHYS_OPT_DESIGN.IS_ENABLED') == '1':
                    (run_dir / f'{top}_postroute_physopt.dcp').write_text('')
            return 'impl_1' if name == 'get_runs' else ''
        return call

    tcl = tkinter.Tcl()
    tcl.createcommand('version', lambda *args: command[command.index('-flow-version') + 1])
    for name in ('set_param', 'open_project', 'get_runs', 'reset_run', 'set_property',
                 'launch_runs', 'wait_on_run', 'close_project'):
        tcl.createcommand(name, record(name))
    tcl.call('set', 'argv', tuple(argv))
    tcl.eval(f'source {{{flow / "implementation.tcl"}}}')

    names = [c[0] for c in calls]
    assert names.index('reset_run') < names.index('set_property') < names.index('launch_runs')
    assert properties == {'STEPS.POST_ROUTE_PHYS_OPT_DESIGN.IS_ENABLED': str(int(enabled)),
                          'STEPS.POST_ROUTE_PHYS_OPT_DESIGN.ARGS.DIRECTIVE': 'AggressiveExplore'}
    # -to_step has no name for the post-route phys_opt step (Vivado 12-1015)
    launch = next(c for c in calls if c[0] == 'launch_runs')
    assert '-to_step' not in launch
