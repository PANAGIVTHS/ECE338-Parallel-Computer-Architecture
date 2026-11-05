"""The gpgpu commands. Categories come from the plugins; this file knows none of their names."""
import json
import os
import sys
from collections.abc import Callable, Iterable

import typer
import typer.completion
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from typer.core import TyperCommand

from gpgpu.api import GpgpuError, SyncReport, Task
from gpgpu.bootstrap import load_registry, open_workspace

from .completion import SCRIPTS

typer.completion.completion_init()
app = typer.Typer(name="gpgpu", help="Build, test and operate the ECE338 GPGPU.", no_args_is_help=True,
                  add_completion=False, pretty_exceptions_enable=False)
project_app = typer.Typer(help="Keep a GUI-editable design and its committed files in sync.", no_args_is_help=True)
config_app = typer.Typer(help="Inspect the resolved configuration.", no_args_is_help=True)
OTHER = "Other commands"
app.add_typer(project_app, name="project", rich_help_panel=OTHER)
app.add_typer(config_app, name="config", rich_help_panel=OTHER)


def _workspace(ctx: typer.Context):
    """The invocation's workspace, opened once. Tab completion gets here too, where no callback runs."""
    root = ctx.find_root()
    if root.obj is None:
        root.obj = open_workspace(profile=root.params.get("profile") or "default", overrides=root.params.get("set_values") or ())
    return root.obj


def _suggest(ctx: typer.Context, incomplete: str, items: Callable[..., Iterable]) -> list:
    """Suggestions starting with what was typed. A broken configuration suggests nothing."""
    try:
        found = items(_workspace(ctx))
    except GpgpuError:
        return []
    return [item for item in found if (item[0] if isinstance(item, tuple) else item).startswith(incomplete)]


def _complete_keys(ctx: typer.Context, incomplete: str) -> list:
    return _suggest(ctx, incomplete, lambda workspace: workspace.settings.keys())


def _complete_projects(ctx: typer.Context, incomplete: str) -> list:
    return _suggest(ctx, incomplete, lambda workspace: workspace.projects())


@app.callback()
def _root(profile: str = typer.Option("default", "--profile", "-p", help="Profile from config/profiles."),
          set_values: list[str] = typer.Option(None, "--set", metavar="OPTION=VALUE", autocompletion=_complete_keys,
                                               help="Override a known option; repeat for more.")) -> None:
    """Read by _workspace(), when a command first needs it."""


def _rows(tasks: list[Task]) -> Iterable[tuple[str, str]]:
    """One line per description: tasks differing only by a name become programs:<name>:all."""
    groups: dict[str, list[list[str]]] = {}
    for task in tasks:
        groups.setdefault(task.doc, []).append(task.command.split(":"))
    for doc, commands in groups.items():
        yield ":".join(parts[0] if len(set(parts)) == 1 else "<name>" for parts in zip(*commands)), doc


class _CategoryHelp(TyperCommand):
    """Adds the category's tasks to its help page."""

    def format_help(self, ctx, formatter) -> None:
        super().format_help(ctx, formatter)
        table = Table(box=None, show_header=False, padding=(0, 1))
        table.add_column(style="bold bright_green", no_wrap=True)
        table.add_column(overflow="fold")
        for row in _rows(_workspace(ctx).tasks(ctx.info_name)):
            table.add_row(*row)
        Console().print(Panel(table, title="Tasks", title_align="left", border_style="dim"))


def _add_category(category: str, doc: str) -> None:
    def complete(ctx: typer.Context, incomplete: str) -> list:
        return _suggest(ctx, incomplete, lambda workspace: [(task.command, task.doc) for task in workspace.tasks(category)])

    def run(ctx: typer.Context,
            task: str = typer.Argument(..., metavar="TASK", help="The task to run, after its dependencies.", autocompletion=complete),
            plain: bool = typer.Option(False, "--plain", help="Stream plain logs instead of the live monitor.")) -> None:
        monitor = not plain and sys.stdout.isatty() and not os.environ.get("CI")
        raise typer.Exit(_workspace(ctx).run(f"{category}:{task}", monitor=monitor,
                                             warn=lambda message: typer.secho(f"warning: {message}", fg="yellow", err=True)))

    app.command(category, help=doc, cls=_CategoryHelp, no_args_is_help=True, rich_help_panel="Categories")(run)


for _category, _doc in load_registry().categories().items():
    _add_category(_category, _doc)


def _show(report: SyncReport) -> None:
    typer.echo(f"{report.project}: {report.state.value}")
    for label, lines in (("project", report.project_changes), ("source", report.source_changes), ("config", report.config_drift)):
        for line in lines:
            typer.echo(f"  {label + ':':9}{line}")


_project_name = typer.Argument(..., help="The project.", autocompletion=_complete_projects)
_force = typer.Option(False, "--force", help="Discard the other side's changes.")


@project_app.command("list")
def _project_list(ctx: typer.Context) -> None:
    """List the projects."""
    for name in _workspace(ctx).projects():
        typer.echo(name)


@project_app.command("status")
def _project_status(ctx: typer.Context, name: str = _project_name) -> None:
    """Show which side changed since the last sync."""
    _show(_workspace(ctx).status(name))


@project_app.command("pull")
def _project_pull(ctx: typer.Context, name: str = _project_name, force: bool = _force) -> None:
    """Copy edits made in the GUI into the committed files."""
    _show(_workspace(ctx).pull(name, force=force))


@project_app.command("push")
def _project_push(ctx: typer.Context, name: str = _project_name, force: bool = _force) -> None:
    """Rebuild the project from the committed files."""
    _show(_workspace(ctx).push(name, force=force))


@project_app.command("open")
def _project_open(ctx: typer.Context, name: str = _project_name) -> None:
    """Open the project in its GUI, creating it first if needed."""
    _workspace(ctx).open(name)


@config_app.command("show")
def _config_show(ctx: typer.Context, output_format: str = typer.Option("yaml", "--format", help="yaml or json.")) -> None:
    """Print the complete resolved configuration."""
    values = _workspace(ctx).settings.as_dict()
    if output_format not in ("yaml", "json"):
        raise GpgpuError("--format must be yaml or json")
    typer.echo(json.dumps(values, indent=2) if output_format == "json" else yaml.safe_dump(values, sort_keys=False), nl=output_format == "json")


@config_app.command("get")
def _config_get(ctx: typer.Context, key: str = typer.Argument(..., help="Dotted key.", autocompletion=_complete_keys),
                source: bool = typer.Option(False, "--source", help="Also print the layer that set it."),
                resolved_path: bool = typer.Option(False, "--resolved-path", help="Print paths.build.root as an absolute path.")) -> None:
    """Print one resolved value."""
    settings = _workspace(ctx).settings
    if resolved_path:
        if key != "paths.build.root":
            raise GpgpuError("--resolved-path is only supported for paths.build.root")
        typer.echo(settings.build_root)
    else:
        text = yaml.safe_dump(settings.get(key), sort_keys=False).strip()
        typer.echo("\n".join(line for line in text.splitlines() if line != "..."))
    if source:
        typer.echo(f"source: {settings.source_of(key)}")


@config_app.command("validate")
def _config_validate(ctx: typer.Context) -> None:
    """Check the configuration against what every command expects."""
    errors, warnings = _workspace(ctx).validate()
    for label, lines in (("error", errors), ("warning", warnings)):
        for line in lines:
            typer.echo(f"{label}: {line}")
    typer.echo(f"Errors: {len(errors)} | Warnings: {len(warnings)}")
    raise typer.Exit(1 if errors else 0)


@app.command(rich_help_panel=OTHER)
def doctor(ctx: typer.Context) -> None:
    """Check the configured tools, the repository and every command's settings."""
    checks = _workspace(ctx).doctor()
    table = Table(title="GPGPU environment")
    for column in ("Check", "Status", "Detail"):
        table.add_column(column, overflow="fold")
    for check in checks:
        status = "[green]OK[/green]" if check.ok else "[red]FAILED[/red]" if check.required else "[yellow]MISSING[/yellow]"
        table.add_row(check.name, status, check.detail)
    Console().print(table)
    raise typer.Exit(1 if any(check.required and not check.ok for check in checks) else 0)


@app.command(rich_help_panel=OTHER)
def completion(shell: str = typer.Argument(..., help="zsh or bash.", autocompletion=lambda: list(SCRIPTS))) -> None:
    """Print a tab-completion script, to save and load from your shell's rc file."""
    if shell not in SCRIPTS:
        raise GpgpuError(f"No completion for {shell}", f"Available: {', '.join(SCRIPTS)}")
    typer.echo(SCRIPTS[shell])


def main() -> None:
    try:
        app(prog_name="gpgpu")
    except GpgpuError as error:
        typer.secho(f"error: {error.message}", fg="red", err=True)
        if error.hint:
            typer.echo(f"hint: {error.hint}", err=True)
        raise SystemExit(error.exit_code) from None
