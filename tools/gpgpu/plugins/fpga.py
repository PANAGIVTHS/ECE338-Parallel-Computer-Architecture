"""Operate the board: upload, reset, program, and run programs through the monitor."""
from gpgpu.api import Backends, Board, Task


def tasks(backend: Backends) -> list[Task]:
    board = backend(Board)
    boot = board.boot_program()
    host = f"software:programs:{boot}:boot" if boot else "vitis:build:host"
    result = [
        Task("fpga:upload", "Upload the existing bitstream, PS init script and host application (the monitor, or "
             "software.host.boot_program). Builds nothing.", board.upload(), requires=("vivado:system:build", host)),
        Task("fpga:reset", "Reset the board, keeping its current mode.", board.reset()),
        Task("fpga:mode:project", "Set PROJECT mode, without resetting or programming.", board.set_mode("project")),
        Task("fpga:mode:demo", "Set DEMO mode, without resetting or programming.", board.set_mode("demo")),
        Task("fpga:preflight", "Check that all uploaded files are on the machine connected to the board. Read-only.",
             board.preflight()),
        Task("fpga:program:reset", "Reset the board, once preflight has passed.",
             board.reset(), needs=("fpga:preflight",)),
        Task("fpga:program", "Preflight, reset, set PROJECT mode, program the fabric, then start the host application.",
             board.program(), needs=("fpga:program:reset",), setup=("fpga:mode:project",)),
        Task("fpga:deploy", "Upload the existing files, then run the whole fpga program sequence. Builds nothing.",
             needs=("fpga:upload",), setup=("fpga:program",)),
    ]
    for program in board.programs():
        result.append(Task(f"fpga:programs:{program}:run",
                           "Build the program for the A9, send it to the monitor over UART and run it "
                           "(software.runtime.arguments); its status is the task's.",
                           board.run_program(program), needs=(f"software:programs:{program}:host",)))
    return result
