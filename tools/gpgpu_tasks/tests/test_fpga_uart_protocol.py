"""Exercise the VM driver with the real UART client and a PTY host monitor."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import pty
import select
import struct
import threading
import tty

import pytest

ROOT = Path(__file__).resolve().parents[3]


def test_fpga_task_discovery_does_not_require_repo_on_pythonpath(tmp_path):
    import subprocess
    import sys
    import json

    source = (
        "import importlib.util; from pathlib import Path; from config import resolve_config; "
        f"root=Path({str(ROOT)!r}); "
        "spec=importlib.util.spec_from_file_location('outside_cwd_tasks', root/'tools/hardware/fpga/tasks.py'); "
        "module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module); "
        f"config=resolve_config(root, overrides=['paths.build.root={tmp_path / 'build'}']); "
        "print(__import__('json').dumps([task['name'] for task in module.create_tasks(config)]))"
    )
    environment = os.environ.copy()
    environment.pop('PYTHONPATH', None)
    result = subprocess.run([sys.executable, '-c', source], cwd=tmp_path,
                            env=environment, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert 'fpga:programs:simple:all' in json.loads(result.stdout)


def test_run_rechecks_imem_to_prevent_cross_session_program_mixup():
    spec = importlib.util.spec_from_file_location('vm_run_guard', ROOT / 'tools/hardware/fpga/program_uart.py')
    assert spec is not None and spec.loader is not None
    driver = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(driver)
    events = []

    class WrongProgramUart:
        def status(self):
            return dict(idle=1, running=0, busy=0, done=0)

        def dump_imem_ascii(self, count, offset):
            events.append('verify')
            return {0: 'ffffffff'}

        def run(self):
            events.append('run')
            return 'Core entered idle state'


    with pytest.raises(RuntimeError, match='readback|IMEM'):
        driver.execute_uart(WrongProgramUart(), 'run', ['00008067'])
    assert events == ['verify']


@pytest.mark.parametrize('remote_entrypoint', [False, True])
def test_vm_driver_consumes_bulk_load_prompt_before_readback(tmp_path, remote_entrypoint):
    pytest.importorskip("serial")
    spec = importlib.util.spec_from_file_location("vm_driver_test", ROOT / "tools/hardware/fpga/program_uart.py")
    assert spec is not None and spec.loader is not None
    driver = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(driver)
    namespace = {}
    exec((ROOT / "tools/board/xc7z020/uart.py").read_text(), namespace)
    master, slave = pty.openpty()
    tty.setraw(slave)
    stop = threading.Event()
    state = {"memory": [], "commands": [], "idle": True}

    def host():
        pending = bytearray()
        count = None
        while not stop.is_set():
            if not select.select([master], [], [], 0.05)[0]:
                continue
            pending.extend(os.read(master, 65536))
            while pending:
                if count is not None:
                    size = count * 4
                    if len(pending) < size:
                        break
                    state["memory"] = list(struct.unpack("<" + "I" * count, pending[:size]))
                    del pending[:size]
                    count = None
                    os.write(master, b"IMEM_LOAD_COMPLETE\ngpgpu> ")
                    continue
                if b"\n" not in pending:
                    break
                line, _, rest = pending.partition(b"\n")
                pending = bytearray(rest)
                command = line.decode().strip()
                state["commands"].append(command)
                if command.startswith("loadimem_bin "):
                    count = int(command.split()[2])
                    reply = "READY_IMEM_BIN\n"
                elif command.startswith("dumpimem "):
                    offset, size = map(int, command.split()[1:])
                    reply = "".join(f"{i}: {state['memory'][i]:08x}\n" for i in range(offset, offset + size)) + "gpgpu> "
                elif command == "run":
                    state["idle"] = True
                    reply = "Core entered idle state\ngpgpu> "
                else:
                    reply = "STATUS=0x1 idle=1 running=0 busy=0 done=0\ngpgpu> "
                os.write(master, reply.encode())

    worker = threading.Thread(target=host, daemon=True)
    worker.start()
    try:
        if remote_entrypoint:
            exec((ROOT / 'tools/hardware/fpga/program_uart.py').read_text(), namespace)
            image = tmp_path / 'instructions.mem'
            image.write_text('00100093\n00008067\n')
            namespace['remote_main']('load-imem', str(image), os.ttyname(slave), 115200)
            namespace['remote_main']('run', str(image), os.ttyname(slave), 115200)
        else:
            with namespace["GpgpuUartMonitor"](os.ttyname(slave), baud=115200) as uart:
                driver.execute_uart(uart, "load-imem", ["00100093", "00008067"])
                driver.execute_uart(uart, "run", ["00100093", "00008067"])
        assert state["memory"] == [0x00100093, 0x00008067]
        assert state["idle"]
        assert "dumpimem 0 2" in state["commands"]
        assert state["commands"].count("run") == 1
        assert "done" not in state["commands"]
    finally:
        stop.set()
        worker.join(2)
        os.close(master)
        os.close(slave)


def load_module(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MONITOR_STATUS = """INFO = 0x00020020
STATUS = 0x{status:08x}
  idle = 1
  running = 0
  stopped = 0
  faulted = {faulted}
  irq_enabled = 0
  irq_pending = 0
FAULT_INFO = 0x00000031
FAULT_LANES = 0xaaaaaaaa
FAULT_PC = 0x00000004
"""


def test_status_parser_reads_faulted_and_the_fault_report():
    uart = load_module('uart_status', 'tools/board/xc7z020/uart.py')
    status = uart.parse_status(MONITOR_STATUS.format(status=0x9, faulted=1))
    assert status['faulted'] == 1
    assert (status['fault_info'], status['fault_lanes'], status['fault_pc']) == (0x31, 0xAAAAAAAA, 4)


@pytest.mark.parametrize('faulted', [0, 1])
def test_checked_state_refuses_a_faulted_gpu_with_its_report(faulted):
    uart = load_module('uart_status', 'tools/board/xc7z020/uart.py')
    driver = load_module('vm_fault_guard', 'tools/hardware/fpga/program_uart.py')

    class Monitor:
        def status(self):
            return uart.parse_status(MONITOR_STATUS.format(status=0x1 | faulted << 3, faulted=faulted))

    if not faulted:
        assert driver.checked_state(Monitor()) == 'idle'
        return
    with pytest.raises(RuntimeError, match=r'FAULTED: fault_info=0x00000031, fault_lanes=0xaaaaaaaa, '
                                           r'fault_pc=0x00000004.*clear'):
        driver.checked_state(Monitor())
