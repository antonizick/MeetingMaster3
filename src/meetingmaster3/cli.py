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


@app.command()
def doctor(
    refresh: bool = typer.Option(True, help="Re-run hardware detection instead of using a cache."),
) -> None:
    """Report hardware, the chosen profile, recommendations and environment checks."""
    from meetingmaster3.hardware.detect import get_hardware
    from meetingmaster3.hardware.doctor import run_checks
    from meetingmaster3.hardware.recommend import format_eta, recommend

    settings = load_settings()
    info = get_hardware(refresh=refresh)
    rec = recommend(info, settings.hardware.profile)
    t = rec.transcription

    typer.secho("Hardware", bold=True)
    if info.gpus:
        for gpu in info.gpus:
            typer.echo(
                f"  GPU: {gpu.name}, {gpu.vram_total_mb / 1024:.1f} GB VRAM "
                f"({gpu.vram_free_mb / 1024:.1f} GB free), driver {gpu.driver_version or '?'}"
            )
    else:
        typer.echo("  GPU: none detected")
    typer.echo(f"  CPU: {info.cpu_name or 'unknown'} ({info.cpu_cores} threads)")
    typer.echo(f"  RAM: {info.ram_total_mb / 1024:.1f} GB")
    suffix = " (set in settings)" if rec.overridden else " (auto-detected)"
    typer.echo(f"  Profile: {rec.profile} / {rec.profile_label}{suffix}")

    typer.secho("Recommended transcription", bold=True)
    typer.echo(f"  Model: {t.model} ({t.compute_type}, batch size {t.batch_size})")
    typer.echo(f"  Alternatives: {', '.join(t.alternatives) or 'none'}")
    typer.echo(f"  Diarization: {t.diarize}")
    low, high = t.estimate(3600)
    typer.echo(
        f"  Speed: {t.rtf_low:g}-{t.rtf_high:g}x real time ({t.status}); "
        f"a 60-minute meeting takes {format_eta(low, high)}"
    )
    typer.echo(f"  {t.notes}")

    typer.secho("Recommended local LLM (Ollama)", bold=True)
    typer.echo(f"  {rec.llm.summary}")
    for m in rec.llm.models:
        typer.echo(f"  - {m.family} {m.quant}: context {m.context}, quality {m.quality}, {m.speed}")
    typer.echo(f"  {rec.llm.context_note}")
    typer.echo(f"  {rec.llm.vram_handoff}")

    if rec.warnings:
        typer.secho("Warnings", bold=True)
        for w in rec.warnings:
            typer.echo(f"  [{w.severity}] {w.message}")

    typer.secho("Environment", bold=True)
    checks = run_checks(settings, resolve_paths())
    marks = {"ok": ("OK  ", typer.colors.GREEN), "warn": ("WARN", typer.colors.YELLOW)}
    for c in checks:
        mark, color = marks.get(c.status, ("FAIL", typer.colors.RED))
        typer.echo("  ", nl=False)
        typer.secho(mark, fg=color, nl=False)
        typer.echo(f" {c.name}: {c.detail}")
        if c.hint and c.status != "ok":
            typer.echo(f"       {c.hint}")
    if any(c.blocking for c in checks):
        typer.secho("Blocking problems found.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)


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
