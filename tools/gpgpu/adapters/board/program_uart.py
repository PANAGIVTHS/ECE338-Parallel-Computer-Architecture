"""VM-side driver, executed after the unmodified shared UART client source.

No repository imports: the SSH wrapper supplies the UART client's namespace.
"""

from pathlib import Path
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


def remote_run(elf_path, port, baud, arguments, timeout):
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
            status = uart.run_program(arguments, timeout)
        finally:
            uart.close()
    print(f'{arguments[0]} returned {status}', flush=True)
    if status != 0:
        raise SystemExit(status if 0 < status < 256 else 1)
