"""VM-side driver, executed after the unmodified shared UART client source.

No repository imports: the SSH wrapper supplies the UART client's namespace.
"""

from pathlib import Path
import json
import re
import fcntl
import hashlib
import os
from contextlib import contextmanager


@contextmanager
def uart_ownership(port, lock_path=None):
    """Nonblocking advisory lock shared by sudo/non-sudo CLI sessions."""
    path = lock_path or ('/tmp/gpgpu-uart-' + hashlib.sha256(port.encode()).hexdigest() + '.lock')
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o666)
    try:
        # Creation mode is affected by umask. Permit configured non-sudo users
        # to cooperate with sudo sessions; never unlink a live lock inode.
        if os.fstat(fd).st_uid == os.geteuid():
            os.fchmod(fd, 0o666)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(f'UART already owned by another CLI session: {port}') from exc
        yield
    finally:
        os.close(fd)


def exclusive_monitor(port, baud, verbose):
    """Reuse all protocol methods; specialize only Linux serial acquisition."""
    if serial is None:
        raise RuntimeError('VM Python requires pyserial installed before UART use')
    class ExclusiveMonitor(GpgpuUartMonitor):
        def __init__(self):
            self.ser = serial.Serial(port, baudrate=baud, timeout=2.0, exclusive=True)
            try:
                self.verbose = verbose
                self.rx_buffer = bytearray()
                time.sleep(0.2)
                self.flush()
            except BaseException:
                self.ser.close()
                raise
    return ExclusiveMonitor()


def remote_main(operation, imem, port, baud, layout_path):
    if operation not in ('load-imem', 'run'):
        raise ValueError('Unknown UART operation')
    words = validated_words(imem)
    layout = json.loads(Path(layout_path).read_text())
    image = read_gmem_image(Path(layout_path).with_name(layout['gmem_image']))
    with uart_ownership(port):
        uart = exclusive_monitor(port, baud, verbose=True)
        try:
            execute_uart(uart, operation, words, layout, image)
        finally:
            uart.close()


def remote_exec(elf_path, port, baud, arguments, timeout):
    """Load an A9 program through the monitor's loader, run it and exit with its status."""
    entry, segments = elf_load_segments(Path(elf_path).read_bytes())
    size = sum(len(data) for _, data in segments)
    with uart_ownership(port):
        uart = exclusive_monitor(port, baud, verbose=False)
        try:
            uart.write_line('')
            uart.wait_prompt(timeout=10.0)
            print(f'Loading {Path(elf_path).name}: {len(segments)} segments, {size} bytes '
                  f'(about {size * 10 // baud + 1} s at {baud} baud)', flush=True)
            uart.load_program(entry, segments)
            status = uart.exec_program(arguments, timeout)
        finally:
            uart.close()
    print(f'{arguments[0]} returned {status}', flush=True)
    if status != 0:
        raise SystemExit(status if 0 < status < 256 else 1)


def validated_words(path):
    """Reject malformed/overflowing images before serial is opened."""
    words = [line.strip().lower() for line in Path(path).read_text().splitlines() if line.strip()]
    if not words or len(words) > DEPTH or any(not re.fullmatch(r'[0-9a-f]{8}', word) for word in words):
        raise ValueError(f'IMEM must contain 1..{DEPTH} words of exactly 8 hex digits')
    return words


def checked_state(uart):
    """Fail closed on incomplete, contradictory or running/busy status."""
    status = uart.status()
    if any(re.search(rf'\b{name}\s*=', str(status.get('text', '')))
           for name in ('loading', 'dumping')) or any(name in status for name in ('loading', 'dumping')):
        raise RuntimeError(
            'Incompatible legacy UART status (loading/dumping). Build and deploy '
            'matching idle/running PL and host ELF before loading programs. '
            f'Status: {status}'
        )
    keys = ('idle', 'running', 'stopped', 'faulted')
    if (any(type(status.get(key)) is not int or status[key] not in (0, 1) for key in keys)
            or 'ERROR' in str(status.get('text', ''))
            or status['running'] or status['idle'] != 1):
        raise RuntimeError(f'Unsafe or malformed UART status: {status}')
    if status['faulted']:
        # The host monitor leaves FAULTED set until `clear`, so a faulting run
        # is reported here even though the run command itself returned.
        raise RuntimeError(
            'GPU FAULTED: '
            + ', '.join(f'{name}=0x{status[name]:08x}' for name in ('fault_info', 'fault_lanes', 'fault_pc')
                        if name in status)
            + ". Acknowledge it with the monitor's `clear` command."
        )
    return 'idle'


def execute_uart(uart, operation, words, layout, image):
    """One guarded program load (IMEM and data) with readback, or a single launch.

    The load writes IMEM, the .rodata/.data image into GMEM and zeroes .bss and
    .shared (linker.ld); it never writes GPGPU_ARGS."""
    if operation not in ('load-imem', 'run'):
        raise ValueError('Unknown UART operation')
    checked_state(uart)
    if operation == 'load-imem':
        print(uart.load_imem_bin(words, offset=0), flush=True)
        if uart.dump_imem_ascii(len(words), offset=0) != dict(enumerate(words)):
            raise RuntimeError('IMEM readback mismatch')
        print(f'Verified {len(words)} IMEM words', flush=True)
        load_program_data(uart, layout, image, verify=True)
        print(f'Loaded and verified {len(image)} GMEM data words; zeroed .bss and .shared', flush=True)
    else:
        # Another CLI workflow can load a different program between dependency
        # stages. Recheck under this session's UART lock before launching.
        if uart.dump_imem_ascii(len(words), offset=0) != dict(enumerate(words)):
            raise RuntimeError('IMEM readback mismatch before run')
        print(uart.run(), flush=True)
        checked_state(uart)
