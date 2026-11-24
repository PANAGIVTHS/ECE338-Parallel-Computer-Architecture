"""Operate the board: upload, reset, program, and load and run programs."""
from gpgpu.api import Backends, Board, Task


def tasks(backend: Backends) -> list[Task]:
    board = backend(Board)
    result = [
        Task("fpga:upload", "Upload the existing bitstream, PS init script and host application. Builds nothing.",
             board.upload(), requires=("vivado:system:build", "vitis:build:host")),
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
        prefix = f"fpga:programs:{program}"
        result += [
            Task(f"{prefix}:upload", "Build the memory image of the program and upload it.", board.upload_program(program),
                 needs=(f"software:programs:{program}:riscv:build", f"software:programs:{program}:mem")),
            Task(f"{prefix}:load-imem", "After upload, load and verify IMEM over UART. No reset or programming.",
                 board.load_program(program), needs=(f"{prefix}:upload",)),
            Task(f"{prefix}:run", "After load-imem, run the kernel once and verify it returns to idle.",
                 board.run_program(program), needs=(f"{prefix}:load-imem",)),
            Task(f"{prefix}:all", "Build, upload, load and run the program.", needs=(f"{prefix}:run",)),
        ]
    return result
