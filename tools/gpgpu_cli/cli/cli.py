"""Typer application construction and global configuration resolution."""

from __future__ import annotations

import os
from pathlib import Path
import sys

import typer

from .commands.config import app as config_app
from .commands.doctor import doctor
from .commands.run import TaskHelpCommand, run
from config import ConfigError, RepoNotFoundError, find_repo_root, resolve_config


def create_app(*, repo_root: str | Path | None = None) -> typer.Typer:
    """Create the CLI application, optionally pinned to a root for tests."""

    app = typer.Typer(
        name="gpgpu",
        help="Build, test, and operate the ECE338 GPGPU project.",
        no_args_is_help=True,
        add_completion=True,
        rich_markup_mode="rich",
    )
    app.add_typer(config_app, name="config")
    app.command()(doctor)
    app.command(cls=TaskHelpCommand)(run)

    def root() -> Path:
        return Path(repo_root).resolve() if repo_root is not None else find_repo_root()

    @app.callback()
    def callback(
        ctx: typer.Context,
        profile: str = typer.Option(
            "default", "--profile", "-p", help="Profile from config/profiles."
        ),
        set_values: list[str] | None = typer.Option(
            None,
            "--set",
            metavar="OPTION=VALUE",
            help="Override a known option; repeat for multiple values.",
        ),
    ) -> None:
        """Resolve configuration once, before dispatching a command."""

        try:
            repository = root()
            ctx.obj = resolve_config(
                repository,
                profile=profile,
                overrides=set_values or (),
            )
        except (RepoNotFoundError, ConfigError) as exc:
            raise typer.BadParameter(str(exc)) from exc

    return app


# Set by the repository launcher (./gpgpu) before it runs this entry point.
LAUNCHER_ENVIRONMENT = "GPGPU_LAUNCHER"


def main() -> None:
    # The launcher keeps .venv in sync with the dependency files. The console
    # script of an activated .venv would skip that, so it hands over to the
    # launcher of the repository this environment belongs to (<root>/.venv).
    if LAUNCHER_ENVIRONMENT not in os.environ:
        launcher = Path(sys.prefix).parent / "gpgpu"
        if not launcher.is_file():
            raise SystemExit(f"gpgpu must run through the repository launcher, not found: {launcher}")
        os.execv(launcher, [str(launcher), *sys.argv[1:]])
    create_app()()


if __name__ == "__main__":
    main()
