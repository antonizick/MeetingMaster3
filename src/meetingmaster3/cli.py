"""The ``mm3`` command-line interface."""

from __future__ import annotations

import typer
import uvicorn

from meetingmaster3 import __version__
from meetingmaster3.config.paths import resolve_paths
from meetingmaster3.config.settings import load_settings
from meetingmaster3.logging import configure_logging

app = typer.Typer(help="MeetingMaster3: local-first meeting intelligence.", no_args_is_help=True)
config_app = typer.Typer(help="Inspect configuration.", no_args_is_help=True)
app.add_typer(config_app, name="config")


@app.command()
def version() -> None:
    """Print the version."""
    typer.echo(__version__)


@app.command()
def serve(
    host: str | None = typer.Option(None, help="Bind address (default from settings)."),
    port: int | None = typer.Option(None, help="Port (default from settings)."),
    reload: bool = typer.Option(False, help="Auto-reload on code changes (development)."),
) -> None:
    """Start the web app."""
    configure_logging()
    settings = load_settings()
    if host is not None:
        settings.server.host = host
    if port is not None:
        settings.server.port = port
    resolve_paths().ensure()
    if not settings.is_loopback:
        typer.secho(
            f"WARNING: binding to {settings.server.host}. MeetingMaster3 has no authentication; "
            "anyone who can reach this address can read your meetings. "
            "Use 127.0.0.1 unless you know what you are doing. Requests are only accepted for "
            "hosts listed in server.allowed_hosts.",
            fg=typer.colors.RED,
            err=True,
        )
    if reload:
        uvicorn.run(
            "meetingmaster3.app:create_app",
            factory=True,
            host=settings.server.host,
            port=settings.server.port,
            reload=True,
        )
    else:
        from meetingmaster3.app import create_app

        uvicorn.run(create_app(settings), host=settings.server.host, port=settings.server.port)


@config_app.command("path")
def config_path() -> None:
    """Print the config, data, cache and model paths."""
    p = resolve_paths()
    typer.echo(f"config_file: {p.config_file}")
    typer.echo(f"data_dir:    {p.data_dir}")
    typer.echo(f"cache_dir:   {p.cache_dir}")
    typer.echo(f"models_dir:  {p.models_dir}")


@config_app.command("show")
def config_show() -> None:
    """Print the effective settings with secrets masked."""
    import yaml

    typer.echo(yaml.safe_dump(load_settings().dump_masked(), sort_keys=False))


def main() -> None:
    app()
