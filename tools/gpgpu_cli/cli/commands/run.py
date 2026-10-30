"""Execute one pydoit task from the resolved project graph."""

from __future__ import annotations

import re

import typer
from rich.console import Console, Group
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from src import run_logged_task
from typer.core import TyperCommand

from config import ConfigError, ResolvedConfig

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

• `tests:rtl:e2e:build` — Build the E2E bench (`tests.rtl.e2e.testbench`/`top`) with Verilator over `hardware.sources` minus `tests.rtl.e2e.exclude_sources`.

• `tests:rtl:e2e:run` — Run the end-to-end suite with `tests.rtl.e2e.plusargs`: load, launch, and check DMEM only through AXI4-Lite and the IRQ.

• `tests:rtl:e2e:all` — Generate, build, and run the E2E suite. Set `tests.rtl.trace.enabled=true` for waveform tracing.

• `tests:rtl:smx:build` — Build `tb_GPGPU.sv` with Verilator (top `tb_GPGPU_smx_only`).

• `tests:rtl:smx:run` — Run the SMX-only suite with direct memory access.

• `tests:rtl:smx:all` — Generate, build, and run the SMX-only suite. Set `tests.rtl.trace.enabled=true` for waveform tracing.

• `tests:rtl:random` — Generate and run reproducible random programs on the SMX testbench. Configure the run with `tests.rtl.random.iterations` and `tests.rtl.random.seed`.

• `tests:rtl:build` — Build the SMX and E2E suites.

• `tests:rtl:run` — Run the SMX and E2E suites.

• `tests:rtl:all` — Generate, build, and run the SMX and E2E suites.

[bold cyan]Vivado[/bold cyan]

The public dependency chain is: IP project → IP package → Zynq system/BD/wrapper → synthesis/implementation/bitstream/XSA → Vitis.

• `vivado:ip:create` — Recreate the managed `gpgpu_ip_dev` development project from production RTL. No packaging or system synthesis.

• `vivado:ip:build` — Package and validate `user.org:user:gpgpu_axi:1.0`, then safely publish the self-contained IP repository. No standalone bitstream.

• `vivado:system:create` — Register the packaged IP catalog, create or preserve the managed `gpgpu_system` BD, apply configured cores/AXI address, and generate products/wrapper. Existing reference projects are protected; use a fresh build root.

• `vivado:system:build` — Run cached synthesis, implementation, bitstream and XSA stages. Publish `hardware/bitstream/<top>.bit` and `hardware/platform/<xsa_name>.xsa` under the build root.

[bold cyan]Vitis[/bold cyan]

The dependency chain is: Vivado XSA → editable Vitis project → platform build → host build.

• `vitis:project` — Materialize the committed portable default project under `build/software/vitis/` and bind it to the current checkout's XSA and host sources. The generated project can be opened and edited in Vitis.

• `vitis:build:platform` — Build `gpgpu_platform` and verify its `.xsa`, `.xpfm`, and `ps7_init.tcl` outputs.

• `vitis:build:host` — Build `gpgpu_host` after the platform and verify `gpgpu_host.elf`.

• `vitis:build:all` — Run the complete Vitis dependency chain through the host ELF.

• `vitis:export` — Explicitly replace the committed default-project archive with a normalized snapshot of the editable generated project. Build products and machine-specific checkout paths are excluded.

[bold cyan]FPGA[/bold cyan]

• `fpga:programs:<program>:upload` — Build RISC-V assembly and IMEM, then SCP only `<program>_instructions.mem` to the VM upload directory.

• `fpga:programs:<program>:load-imem` — After upload, binary-load and verify IMEM through the VM UART monitor. Configure `hardware.fpga.uart.*`; no reset, mode change or board programming.

• `fpga:programs:<program>:run` — After verified IMEM load, launch once and verify return to idle. DMEM is retained; no adapter initialization, CSV or visualization.

• `fpga:programs:<program>:all` — RISC-V build → mem → upload → load-imem → run. Remote actions repeat on every invocation.

• `fpga:upload` — Upload without building via SCP: existing Vivado bitstream, Vitis `ps7_init.tcl`, and host ELF to the board-connected VM. Configure `hardware.fpga.upload.destination` and `hardware.fpga.upload.directory`.

• `fpga:reset` — SSH to the Debian VM and run its installed `fr` shell shortcut through interactive Bash, preserving the current mode.

• `fpga:mode:project` — Set PROJECT mode without resetting or programming.

• `fpga:mode:demo` — Set DEMO mode without resetting or programming.

• `fpga:preflight` — Read-only SSH `test -f` of all three files in the VM upload directory, with programming configuration validation before any board mutation. Does not prove Agent/container mount visibility.

• `fpga:program:reset` — Programming-scoped reset after successful preflight; standalone `fpga:reset` remains independent of files.

• `fpga:program` — Preflight all uploaded files → reset → PROJECT mode → program PL → initialize PS and run the host ELF. Missing/non-file inputs stop before reset or programming. No build or upload is triggered. Configure `hardware.fpga.agent.*` and `tools.ssh.command`.

• `fpga:deploy` — Upload existing local artifacts → preflight → reset → PROJECT mode → program PL and PS. Upload failure stops before preflight or board mutation. No build is triggered; upload and programming repeat on every invocation.
"""


def _format_task_help(text: str) -> str:
    """Render task identifiers and inline references using terminal styles."""
    def highlight(match: re.Match[str]) -> str:
        value = match[1]
        style = (
            "bold bright_green"
            if value.startswith(("software:programs:", "tests:rtl:", "vivado:", "vitis:", "fpga:"))
            else "yellow"
        )
        return f"[{style}]{escape(value)}[/{style}]"

    return re.sub(r"`([^`]+)`", highlight, text)


class TaskHelpCommand(TyperCommand):
    """Keep argument help compact and render its catalog as real Rich tables."""

    def format_help(self, ctx: typer.Context, formatter: object) -> None:
        super().format_help(ctx, formatter)
        console = Console()
        blocks = []
        table = None
        # Blank paragraphs delimit headings, notes, and task entries. Multiline
        # descriptions are kept together in a single table cell.
        for paragraph in _TASK_HELP.split("\n\n")[2:]:
            paragraph = " ".join(paragraph.splitlines()).strip()
            if not paragraph:
                continue
            entry = re.fullmatch(r"• `([^`]+)` — (.+)", paragraph)
            if entry:
                if table is None:
                    table = Table(
                        box=None, expand=True, padding=(0, 1),
                        header_style="bold", show_edge=False,
                    )
                    table.add_column(
                        "Command", style="bold bright_green",
                        width=0,
                        overflow="fold",
                    )
                    table.add_column("Description", ratio=1, overflow="fold")
                    blocks.append(table)
                table.columns[0].width = min(
                    max(table.columns[0].width or 0, len(entry[1])),
                    max(12, console.width - 32),
                )
                description = Text.from_markup(_format_task_help(entry[2]))
                if entry[1] == "fpga:upload" and isinstance(ctx.obj, ResolvedConfig):
                    destination = ctx.obj.get("hardware.fpga.upload.destination", None)
                    directory = ctx.obj.get("hardware.fpga.upload.directory", None)
                    if destination is not None and directory is not None:
                        description.append(" Configured values: ")
                        # Append literal text: config values may contain Rich
                        # markup or backticks and must never be interpreted.
                        description.append(str(destination), style="yellow")
                        description.append(", ")
                        description.append(str(directory), style="yellow")
                        description.append(".")
                table.add_row(Text(entry[1]), description)
            else:
                table = None
                if blocks:
                    blocks.append(Text(""))
                blocks.append(Text.from_markup(_format_task_help(paragraph)))
        console.print(Panel(Group(*blocks), title="Possible values", border_style="dim"))


def run(
    ctx: typer.Context,
    task: str = typer.Argument(..., metavar="TASK", help=_TASK_HELP.split("\n\n", 1)[0]),
    plain: bool = typer.Option(
        False, "--plain", help="Stream plain logs instead of the interactive build monitor."
    ),
) -> None:
    """Run one task and all of its dependencies from the GPGPU build graph."""

    config: ResolvedConfig = ctx.obj
    try:
        _ = config.build_root
    except ConfigError as exc:
        raise typer.BadParameter(str(exc)) from exc
    status = run_logged_task(config, task, monitor=False) if plain else run_logged_task(config, task)
    if status:
        raise typer.Exit(status)
