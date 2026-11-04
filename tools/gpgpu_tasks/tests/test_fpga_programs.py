from pathlib import Path
import shlex


def test_uart_transport_streams_existing_client(tmp_path, monkeypatch):
    config = upload_config(tmp_path)
    calls = []
    monkeypatch.setattr('subprocess.run', lambda argv, **kw: calls.append((argv, kw)))
    module = fpga_module()
    assert hasattr(module, 'run_program_uart')
    module.run_program_uart(config, 'simple', 'load-imem')
    argv, kwargs = calls[0]
    assert argv[:6] == ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', '--']
    assert shlex.split(argv[-1]) == ['sudo', '-n', 'python3', '-']
    assert 'class GpgpuUartMonitor' in kwargs['input']
    assert '/home/njason/upload/simple_instructions.mem' in kwargs['input']
    assert '/app' not in kwargs['input']
    compile(kwargs['input'], '<remote>', 'exec')
    assert kwargs['check'] and kwargs['text']

from test_fpga_tasks import fpga_module, upload_config, execute, REPO_ROOT
import pytest


def test_uart_config_defaults(tmp_path):
    config = upload_config(tmp_path)
    assert config.get('hardware.fpga.uart.port', None) == '/dev/ttyUSB0'
    assert config.get('hardware.fpga.uart.baud', None) == 115200
    assert config.get('hardware.fpga.uart.sudo', None) is True
    assert config.get('hardware.fpga.uart.python', None) == 'python3'


def driver():
    path = REPO_ROOT / 'tools/hardware/fpga/program_uart.py'
    assert path.is_file(), 'Remote UART driver missing'
    namespace = {}
    exec((REPO_ROOT / 'tools/board/xc7z020/uart.py').read_text(), namespace)
    exec(path.read_text(), namespace)
    return namespace


class FakeUart:
    def __init__(self):
        self.events = []
        self.state = 'idle'
        self.words = {}

    def status(self):
        return dict(idle=int(self.state == 'idle'), running=int(self.state == 'running'), busy=0, done=0)

    def load_imem_bin(self, words, offset):
        assert offset == 0
        self.events.append('load')
        self.words = dict(enumerate(words))
        return 'IMEM_LOAD_COMPLETE'

    def wait_prompt(self):
        return 'gpgpu>'

    def dump_imem_ascii(self, count, offset):
        self.events.append('verify')
        return self.words

    def run(self):
        self.events.append('run')
        self.state = 'idle'
        return 'Core entered idle state'


def test_remote_load_verifies_then_run_returns_to_idle(tmp_path):
    ns = driver()
    path = tmp_path / 'instructions.mem'
    path.write_text('00008067\nABCDEF01\n')
    uart = FakeUart()
    words = ns['validated_words'](path)
    ns['execute_uart'](uart, 'load-imem', words)
    ns['execute_uart'](uart, 'run', words)
    assert uart.events == ['load', 'verify', 'verify', 'run']
    assert uart.state == 'idle'
    assert uart.words == {0: '00008067', 1: 'abcdef01'}



@pytest.mark.parametrize('content', ['', '100000000\n', '-0000001\n', '0x000001\n', 'xyz\n', '00008067\n' * 2049])
def test_preflight_rejects_invalid_memory(tmp_path, content):
    path = tmp_path / 'bad.mem'
    path.write_text(content)
    with pytest.raises(ValueError, match='IMEM'):
        driver()['validated_words'](path)


@pytest.mark.parametrize('status', [
    {}, dict(idle=1, running=1, busy=0, done=0),
    dict(idle=1, running=0, busy=1, done=0),
    dict(idle=0, running=0, busy=0, done=0),
    dict(idle=True, running=0, busy=0, done=0),
    dict(idle=1, running=0, busy=0, done=2),
    dict(idle=1, running=0, busy=0),
    dict(idle=1, running=0, busy=0, done=0, text='ERROR'),
    dict(loading=1, running=0, dumping=0, busy=0, done=0),
])
def test_bad_state_never_mutates_uart(status):
    uart = FakeUart()
    uart.status = lambda: status
    with pytest.raises(RuntimeError, match='status|state'):
        driver()['execute_uart'](uart, 'load-imem', ['00008067'])
    assert uart.events == []


def test_legacy_status_from_real_parser_requires_new_host_without_mutation():
    ns = driver()
    text = 'STATUS = 0x00000001\nloading = 1\nrunning = 0\ndumping = 0\nbusy = 0\ndone = 0\ngpgpu>'
    uart = FakeUart()
    uart.status = lambda: ns['parse_status'](text)
    with pytest.raises(RuntimeError, match='legacy UART status.*'):
        ns['execute_uart'](uart, 'load-imem', ['00008067'])
    assert uart.events == []


def test_readback_failure_prevents_success():
    uart = FakeUart()
    uart.dump_imem_ascii = lambda *a, **kw: {0: 'ffffffff'}
    with pytest.raises(RuntimeError, match='readback'):
        driver()['execute_uart'](uart, 'load-imem', ['00008067'])
    assert uart.events == ['load']


def test_unknown_remote_operation_never_writes():
    uart = FakeUart()
    with pytest.raises(ValueError):
        driver()['execute_uart'](uart, 'reset', ['00008067'])
    assert uart.events == []


def test_vm_entry_preflights_and_closes_exclusive_session(tmp_path):
    ns = driver()
    assert 'remote_main' in ns, 'VM entry point missing'
    events = []
    class Session(FakeUart):
        def __init__(self, port, baud, verbose):
            super().__init__()
            events.append(('open', port, baud))
        def close(self):
            events.append('close')
    from contextlib import contextmanager
    @contextmanager
    def ownership(port):
        events.append('lock')
        yield
        events.append('unlock')
    ns['exclusive_monitor'] = Session
    ns['uart_ownership'] = ownership
    path = tmp_path / 'imem'
    path.write_text('invalid')
    with pytest.raises(ValueError):
        ns['remote_main']('load-imem', str(path), '/dev/ttyUSB0', 115200)
    assert events == []
    path.write_text('00008067\n')
    ns['remote_main']('load-imem', str(path), '/dev/ttyUSB0', 115200)
    assert events == ['lock', ('open', '/dev/ttyUSB0', 115200), 'close', 'unlock']


def test_vm_lock_refuses_concurrent_session(tmp_path):
    ns = driver()
    assert 'uart_ownership' in ns
    lock = tmp_path / 'uart.lock'
    with ns['uart_ownership']('/dev/ttyUSB0', lock_path=lock):
        with pytest.raises(RuntimeError, match='owned'):
            with ns['uart_ownership']('/dev/ttyUSB0', lock_path=lock):
                pytest.fail('second session acquired ownership')


def test_serial_open_is_exclusive_without_editing_shared_client(monkeypatch):
    ns = driver()
    assert 'exclusive_monitor' in ns
    import types
    calls = []
    class Serial:
        def __init__(self, *args, **kwargs):
            calls.append(kwargs)
        def reset_input_buffer(self): pass
        def reset_output_buffer(self): pass
        def close(self): pass
    ns['serial'] = types.SimpleNamespace(Serial=Serial)
    monkeypatch.setattr(ns['time'], 'sleep', lambda _: None)
    monitor = ns['exclusive_monitor']('/dev/ttyUSB0', 115200, verbose=True)
    monitor.close()
    assert calls == [dict(baudrate=115200, timeout=2.0, exclusive=True)]


def test_run_help_lists_uart_program_chain(tmp_path, monkeypatch):
    from cli.cli import create_app
    from typer.testing import CliRunner
    monkeypatch.setenv('COLUMNS', '180')
    result = CliRunner().invoke(create_app(repo_root=REPO_ROOT), ['run', '--help'])
    assert result.exit_code == 0
    for suffix in ('upload', 'load-imem', 'run', 'all'):
        assert f'fpga:programs:<program>:{suffix}' in result.output
    assert 'hardware.fpga.uart' in result.output


def test_run_refuses_false_idle_transition():
    uart = FakeUart()
    uart.words = {0: '00008067'}
    def still_running():
        uart.events.append('run')
        uart.state = 'running'
        return 'Core entered idle state'
    uart.run = still_running
    with pytest.raises(RuntimeError, match='status|idle'):
        driver()['execute_uart'](uart, 'run', ['00008067'])
    assert uart.events == ['verify', 'run']


@pytest.mark.parametrize('failure', ['', 'load-imem'])
def test_real_cli_repeats_remote_actions_and_stops_on_failure(tmp_path, monkeypatch, failure):
    import shutil
    import sys
    import json
    from cli.cli import create_app
    from typer.testing import CliRunner
    import src.doit as runner
    repo = tmp_path / 'repo'
    files = ('config/profiles/default.yaml', 'tools/hardware/fpga/tasks.py',
             'tools/hardware/fpga/program_uart.py', 'tools/board/xc7z020/uart.py',
             'tools/software/programs.py', 'software/programs/simple/simple.c', 'software/programs/gpgpu.ld')
    for name in files:
        dest = repo / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / name, dest)
    events = tmp_path / 'events'
    monkeypatch.setenv('FPGA_EVENTS', str(events))
    monkeypatch.setenv('FPGA_FAIL', failure)
    script = '''import os, sys, ast
from pathlib import Path
name = Path(sys.argv[0]).name
if name.endswith('-gcc'):
    output = Path(sys.argv[sys.argv.index('-o') + 1])
    output.write_text('fake ELF')
    for arg in sys.argv:
        if arg.startswith('-Wl,-Map,'): Path(arg.split(',', 2)[2]).write_text('fake map')
    event = 'build'
elif name.endswith('objdump'):
    print('  0: 00100093 addi x1,x0,1\\n  4: 00008067 jalr x0,0(x1)')
    event = 'dump'
elif name == 'fake-scp':
    assert sys.argv[-1].endswith('/simple_instructions.mem')
    event = 'upload'
else:
    source = sys.stdin.read()
    compile(source, '<fake SSH received driver>', 'exec')
    call = ast.parse(source).body[-1].value
    event = ast.literal_eval(call.args[0])
with open(os.environ['FPGA_EVENTS'], 'a') as stream: stream.write(event + '\\n')
if event == os.environ.get('FPGA_FAIL'): sys.exit(7)
'''
    executables = {}
    for name in ('fake-gcc', 'fake-objdump', 'fake-scp', 'fake-ssh'):
        executable = tmp_path / name
        executable.write_text(f'#!{sys.executable}\n' + script)
        executable.chmod(0o755)
        executables[name] = executable
    monkeypatch.setattr(runner, '_TASK_MODULES', ('tools/software/programs.py', 'tools/hardware/fpga/tasks.py'))
    arguments = ['--set', f'tools.riscv_gcc.command={executables["fake-gcc"]}',
                 '--set', f'tools.scp.command={executables["fake-scp"]}',
                 '--set', f'tools.ssh.command={executables["fake-ssh"]}',
                 'run', '--plain', 'fpga:programs:simple:all']
    app = create_app(repo_root=repo)
    for _ in range(2):
        result = CliRunner().invoke(app, arguments)
        assert result.exit_code == (2 if failure else 0), result.output
    assert events.read_text().splitlines() == (['build', 'dump', 'upload', 'load-imem', 'upload', 'load-imem'] if failure
                                               else ['build', 'dump', 'upload', 'load-imem', 'run', 'upload', 'load-imem', 'run'])
    data = json.loads((repo / 'logs/latest/run.json').read_text())
    if failure:
        assert data['exit_code'] == 7
        run = next(task for task in data['tasks'] if task['task'] == 'fpga:programs:simple:run')
        assert run['status'] == 'not_run'


def test_program_chain_and_upload(tmp_path, monkeypatch):
    config = upload_config(tmp_path)
    tasks = {t['name']: t for t in fpga_module().create_tasks(config)}
    prefix = 'fpga:programs:simple'
    assert prefix + ':all' in tasks
    assert tasks[prefix + ':all']['actions'] == []
    assert tasks[prefix + ':all']['task_dep'] == [prefix + ':run']
    assert tasks[prefix + ':run']['task_dep'] == [prefix + ':load-imem']
    assert tasks[prefix + ':load-imem']['task_dep'] == [prefix + ':upload']
    assert tasks[prefix + ':upload']['task_dep'] == ['software:programs:simple:riscv:build', 'software:programs:simple:mem']
    for suffix in ('upload', 'load-imem', 'run'):
        assert tasks[prefix + ':' + suffix]['uptodate'] == [False]
    source = config.build_root / 'software/programs/simple/simple_instructions.mem'
    source.parent.mkdir(parents=True)
    source.write_text('00008067\n')
    calls = []
    monkeypatch.setattr('subprocess.run', lambda argv, **kw: calls.append(argv))
    execute(tasks[prefix + ':upload'])
    assert calls == [['scp', '--', str(source), 'njason@192.168.1.13:/home/njason/upload/simple_instructions.mem']]
    assert not any('fpga:programs:__pycache__' in name for name in tasks)
