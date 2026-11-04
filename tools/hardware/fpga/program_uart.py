"""VM-side driver, executed after the unmodified shared UART client source.

No repository imports: the SSH wrapper supplies the UART client's namespace.
"""

from pathlib import Path
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


def remote_main(operation, imem, port, baud):
    if operation not in ('load-imem', 'run'):
        raise ValueError('Unknown UART operation')
    words = validated_words(imem)
    with uart_ownership(port):
        uart = exclusive_monitor(port, baud, verbose=True)
        try:
            execute_uart(uart, operation, words)
        finally:
            uart.close()


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
    keys = ('idle', 'running', 'stopped')
    if (any(type(status.get(key)) is not int or status[key] not in (0, 1) for key in keys)
            or 'ERROR' in str(status.get('text', ''))
            or status['running'] or status['idle'] != 1):
        raise RuntimeError(f'Unsafe or malformed UART status: {status}')
    return 'idle'


def execute_uart(uart, operation, words):
    """One guarded IMEM load/readback or single launch; never initialize DMEM."""
    if operation not in ('load-imem', 'run'):
        raise ValueError('Unknown UART operation')
    checked_state(uart)
    if operation == 'load-imem':
        print(uart.load_imem_bin(words, offset=0), flush=True)
        # The shared binary loader stops at its completion marker, not the
        # following prompt. Consume it before issuing the readback command.
        uart.wait_prompt()
        if uart.dump_imem_ascii(len(words), offset=0) != dict(enumerate(words)):
            raise RuntimeError('IMEM readback mismatch')
        print(f'Verified {len(words)} IMEM words', flush=True)
    else:
        # Another CLI workflow can load a different program between dependency
        # stages. Recheck under this session's UART lock before launching.
        if uart.dump_imem_ascii(len(words), offset=0) != dict(enumerate(words)):
            raise RuntimeError('IMEM readback mismatch before run')
        print(uart.run(), flush=True)
        checked_state(uart)
