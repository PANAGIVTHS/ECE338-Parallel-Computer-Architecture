"""Execute one pydoit task from the resolved project graph."""

from __future__ import annotations

import typer

from config import ResolvedConfig
from src import run as run_doit


_TASK_HELP = """A colon-separated task name from the GPGPU build graph.

Possible values (`<program>` is a directory under `software/programs`):

• `software:programs:<program>:x86` — Build and run the native x86 executable.

• `software:programs:<program>:x86:build` — Build the native x86 executable without running it.

• `software:programs:<program>:elf` — Compile and link the RISC-V ELF executable.

• `software:programs:<program>:dump` — Generate the complete RISC-V disassembly.

• `software:programs:<program>:assembly` — Generate the cleaned RISC-V assembly listing.

• `software:programs:<program>:mem` — Generate the instruction-memory image.

• `software:programs:<program>:riscv:build` — Build the RISC-V program assembly and its dependencies.

• `software:programs:<program>:all` — Build both the native x86 executable and RISC-V assembly.

Example: `software:programs:simple:x86`
"""


def run(
    ctx: typer.Context,
    task: str = typer.Argument(..., metavar="TASK", help=_TASK_HELP),
) -> None:
    """Run one task and all of its dependencies from the GPGPU build graph."""

    config: ResolvedConfig = ctx.obj
    status = run_doit(config, ["run", task])
    if status:
        raise typer.Exit(status)
