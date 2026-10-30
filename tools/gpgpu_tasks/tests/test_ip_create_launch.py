"""Real runner + production Tcl with FAKE Vivado commands; not vendor validation."""
import json
from pathlib import Path
import sys

import pytest

from config import resolve_config
from tools.hardware.vivado import tasks

ROOT = Path(__file__).resolve().parents[3]

FAKE_VENDOR = r'''
import json
from pathlib import Path
import sys
import tkinter

args = sys.argv[1:]
with TRACE.open('a') as stream:
    stream.write(json.dumps(args) + '\n')
# Reproduce the launcher collision even when -version follows -tclargs.
if '-version' in args:
    print('FAKE Vivado 2025.2 version-only launcher response')
    sys.exit(0)
tcl = tkinter.Tcl()
# Model the vendor's startup cache as well as the runner's marker/logs.
(Path.cwd() / '.Xil').mkdir(exist_ok=True)
def create_project(name, directory, *options):
    destination = Path(directory) / (name + '.xpr')
    destination.write_text('FAKE XPR from executing production Tcl, not Vivado\n')
    print('FAKE vendor: production Tcl called create_project', flush=True)
    return name

tcl.createcommand('version', lambda *args: '2025.2')
tcl.createcommand('create_project', create_project)
for command in ('set_property', 'add_files', 'close_project'):
    tcl.createcommand(command, lambda *args: '')
for command in ('current_project', 'get_files', 'get_filesets'):
    tcl.createcommand(command, lambda *args: args[-1] if args else 'project')
tcl.setvar('argv', tcl.call('list', *args[args.index('-tclargs') + 1:]))
try:
    tcl.call('source', args[args.index('-source') + 1])
except tkinter.TclError as exc:
    print(str(exc), file=sys.stderr)
    sys.exit(1)
'''


def launch_setup(tmp_path):
    try:
        import tkinter
    except ImportError as exc:
        pytest.skip(f'Tcl unavailable: {exc}')
    try:
        tkinter.Tcl()
    except tkinter.TclError as exc:
        pytest.skip(f'Tcl unavailable: {exc}')
    trace = tmp_path / 'launcher.jsonl'
    vendor = tmp_path / 'fake-vivado'
    vendor.write_text(f'#!{sys.executable}\nTRACE = __import__("pathlib").Path({str(trace)!r})\n' + FAKE_VENDOR)
    vendor.chmod(0o755)
    config = resolve_config(ROOT, overrides=[
        f'paths.build.root={tmp_path / "build"}',
        f'tools.vivado.command={vendor}',
    ])
    definitions = tasks.create_tasks(config)
    stage = next(task for task in definitions if task['name'] == 'vivado:ip:create')
    action, arguments, kwargs = stage['actions'][0]
    assert kwargs == {}
    return definitions, action, arguments, Path(stage['targets'][0]), trace


def test_batch_arguments_do_not_shadow_real_version_probe(tmp_path):
    definitions, _, arguments, _, trace = launch_setup(tmp_path)
    for stage in definitions:
        command = stage['actions'][0][1][0]
        assert '-version' not in command
        assert command[command.index('-flow-version') + 1] == '2025.2'
    tasks._check_tool(arguments[0][0], '2025.2')
    assert json.loads(trace.read_text().splitlines()[0]) == ['-version']


def test_ip_create_runs_production_tcl_in_runner_prepared_directory(tmp_path, capsys):
    _, action, arguments, target, trace = launch_setup(tmp_path)
    action(*arguments)
    assert target.read_text().startswith('FAKE XPR from executing production Tcl')
    assert 'production Tcl called create_project' in capsys.readouterr().out
    assert (target.parent / '.gpgpu-managed.json').is_file()
    assert (target.parent / '.gpgpu/logs/create_ip_project.console.log').is_file()
    assert (target.parent / '.production-ip-project').is_file()
    memory_init, sources, _ = tasks.production_inputs(resolve_config(ROOT))
    assert sorted(p.name for p in (target.parent / 'src').iterdir()) == sorted(
        p.name for p in (memory_init, *sources))
    invocations = [json.loads(line) for line in trace.read_text().splitlines()]
    assert invocations[0] == ['-version']
    assert '-source' in invocations[1]


@pytest.mark.parametrize('identity', ['unmanaged', 'incompatible'])
def test_ip_create_preserves_foreign_projects_before_vendor_launch(tmp_path, identity):
    _, action, arguments, target, trace = launch_setup(tmp_path)
    target.parent.mkdir(parents=True)
    target.write_text('precious reference project')
    if identity == 'incompatible':
        (target.parent / '.gpgpu-managed.json').write_text(json.dumps({
            'project': target.stem, 'part': 'wrong-part', 'kind': 'ip', 'schema': 1,
        }))
    with pytest.raises(RuntimeError, match='unmanaged|Incompatible'):
        action(*arguments)
    assert target.read_text() == 'precious reference project'
    assert [json.loads(line) for line in trace.read_text().splitlines()] == [['-version']]


@pytest.mark.parametrize('conflict', ['unmanaged', 'project', 'part', 'kind', 'schema', 'invalid_json', 'saved_xpr'])
def test_production_tcl_itself_rejects_foreign_or_populated_state(tmp_path, conflict):
    """Exercise Tcl's guard directly, without the Python preflight masking it."""
    _, _, arguments, target, _ = launch_setup(tmp_path)
    command, repo, directory, name, part, _, _ = arguments
    tasks.prepare_managed_project(directory, name, part, 'ip')
    marker = directory / '.gpgpu-managed.json'
    if conflict == 'unmanaged':
        marker.unlink()
    elif conflict == 'invalid_json':
        marker.write_text('{broken')
    elif conflict == 'saved_xpr':
        target.write_text('precious reference project')
    else:
        identity = json.loads(marker.read_text())
        identity[conflict] = 99 if conflict == 'schema' else 'foreign'
        marker.write_text(json.dumps(identity, sort_keys=True) + '\n')
    before = marker.read_bytes() if marker.exists() else None
    with pytest.raises(RuntimeError, match='Vivado stage create_ip_project failed'):
        tasks.run_vivado(command, repo, directory)
    assert (marker.read_bytes() if marker.exists() else None) == before
    assert not (directory / 'src').exists()
    assert not (directory / '.production-ip-project').exists()
    if conflict == 'saved_xpr':
        assert target.read_text() == 'precious reference project'
    else:
        assert not target.exists()
