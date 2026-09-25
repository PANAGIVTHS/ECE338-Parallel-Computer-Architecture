"""Execute one pydoit task from the resolved project graph."""

from __future__ import annotations

import typer

from config import ResolvedConfig
from src import run as run_doit


_TASK_HELP = """A colon-separated task name from the GPGPU build graph.

Possible values:

[bold cyan]Programs[/bold cyan] (`<program>` is a directory under `software/programs`)

• `software:programs:<program>:x86` — Build and run the native x86 executable.

• `software:programs:<program>:x86:build` — Build the native x86 executable without running it.

• `software:programs:<program>:elf` — Compile and link the RISC-V ELF executable.

• `software:programs:<program>:dump` — Generate the complete RISC-V disassembly.

• `software:programs:<program>:assembly` — Generate the cleaned RISC-V assembly listing.

• `software:programs:<program>:mem` — Generate the instruction-memory image.

• `software:programs:<program>:riscv:build` — Build the RISC-V program assembly and its dependencies.

• `software:programs:<program>:all` — Build both the native x86 executable and RISC-V assembly.

Example: `software:programs:simple:x86`

[bold cyan]Tests[/bold cyan]

• `tests:rtl:generate` — Generate shared test programs and expected-memory files.

• `tests:rtl:e2e:build` — Build the end-to-end `tb_GPGPU_e2e.v` suite.

• `tests:rtl:e2e:run` — Run the end-to-end suite through the host command interface.

• `tests:rtl:e2e:all` — Generate, build, and run the end-to-end suite.

• `tests:rtl:smx:build` — Build the SMX-only `tb_GPGPU.v` suite.

• `tests:rtl:smx:run` — Run the SMX-only suite with direct memory access.

• `tests:rtl:smx:all` — Generate, build, and run the SMX-only suite.

• `tests:rtl:random` — Generate and run reproducible random programs on the SMX testbench. Configure the run with `tests.rtl.random.iterations` and `tests.rtl.random.seed`.

• `tests:rtl:build` — Build both the end-to-end and SMX-only suites.

• `tests:rtl:run` — Run both RTL suites.

• `tests:rtl:all` — Generate, build, and run both RTL suites.
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
