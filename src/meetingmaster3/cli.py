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
llm_app = typer.Typer(help="Inspect LLM backends.", no_args_is_help=True)
app.add_typer(llm_app, name="llm")
jobs_app = typer.Typer(help="Inspect jobs and manage retained audio.", no_args_is_help=True)
app.add_typer(jobs_app, name="jobs")
models_app = typer.Typer(help="Download and inspect transcription models.", no_args_is_help=True)
app.add_typer(models_app, name="models")


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
    whisper_model = (
        t.model if settings.transcription.model == "auto" else settings.transcription.model
    )
    checks = run_checks(settings, resolve_paths(), whisper_model)
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


@llm_app.command("list")
def llm_list() -> None:
    """List configured LLM backends (secrets masked)."""
    from meetingmaster3.llm.registry import BackendRegistry

    registry = BackendRegistry(load_settings())
    for name in registry.names():
        d = registry.describe(name)
        star = "*" if d["is_default"] else " "
        typer.echo(f"{star} {name}: {d['kind']}, {d['badge']}, model={d['default_model'] or '-'}")


@llm_app.command("test")
def llm_test(name: str | None = typer.Argument(None, help="Backend name (default: all).")) -> None:
    """Test connectivity to one or all configured backends."""
    from meetingmaster3.llm.doctor import check_backends

    settings = load_settings()
    checks = [c for c in check_backends(settings) if name is None or c.name.split()[1] == name]
    if not checks:
        typer.secho(f"No backend named {name!r}.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    for c in checks:
        typer.echo(
            f"[{c.status}] {c.name}: {c.detail}" + (f"\n       hint: {c.hint}" if c.hint else "")
        )
    if any(c.status == "fail" for c in checks):
        raise typer.Exit(1)


@jobs_app.command("list")
def jobs_list(limit: int = typer.Option(50, help="How many jobs to show (newest first).")) -> None:
    """List jobs with their status and audio retention."""
    from meetingmaster3.storage.db import Database
    from meetingmaster3.storage.repositories import JobRepository

    paths = resolve_paths()
    paths.ensure()
    db = Database.open(paths.database)
    try:
        for job in JobRepository(db).list_jobs(limit=limit):
            if job.audio_path is None:
                audio = "expired" if job.audio_pruned_at else "none"
            elif job.audio_pinned:
                audio = "pinned"
            elif job.audio_expires_at:
                audio = f"until {job.audio_expires_at:%Y-%m-%d}"
            else:
                audio = "kept"
            typer.echo(
                f"{job.id}  {job.status.value:<17} {job.created_at:%Y-%m-%d %H:%M}  "
                f"audio {audio:<16} {job.title or job.source_filename}"
            )
    finally:
        db.close()


@jobs_app.command("prune")
def jobs_prune(
    dry_run: bool = typer.Option(False, "--dry-run", help="Only list what would be deleted."),
) -> None:
    """Delete retained audio that has expired (pinned meetings are kept)."""
    from meetingmaster3.jobs.retention import prune
    from meetingmaster3.storage.db import Database
    from meetingmaster3.storage.repositories import JobRepository

    settings = load_settings()
    paths = resolve_paths()
    paths.ensure()
    db = Database.open(paths.database)
    try:
        items = prune(JobRepository(db), paths.jobs_dir, settings, dry_run=dry_run)
    finally:
        db.close()
    verb = "Would delete" if dry_run else "Deleted"
    for item in items:
        typer.echo(
            f"{verb} audio of {item.job_id} ({item.title or 'untitled'}): "
            f"{', '.join(item.files) or 'no files'}, {item.bytes / 1_048_576:.1f} MB, "
            f"expired {item.expired_at:%Y-%m-%d}"
        )
    total = sum(i.bytes for i in items) / 1_048_576
    typer.echo(f"{verb} audio of {len(items)} job(s), {total:.1f} MB.")


def _recommended_whisper() -> str:
    from meetingmaster3.hardware.detect import get_hardware
    from meetingmaster3.hardware.recommend import recommend

    settings = load_settings()
    if settings.transcription.model != "auto":
        return settings.transcription.model
    return recommend(get_hardware(), settings.hardware.profile).transcription.model


@models_app.command("status")
def models_status() -> None:
    """Show which transcription models are in the local cache."""
    from meetingmaster3.transcription.models import model_status

    settings = load_settings()
    paths = resolve_paths()
    whisper = sorted({_recommended_whisper(), "large-v3-turbo", "medium", "small"})
    typer.echo(f"Model cache: {paths.models_dir}")
    for m in model_status(paths.models_dir, whisper, settings.transcription.diarization_model):
        mark = "cached " if m.cached else "missing"
        typer.echo(f"  [{mark}] {m.kind:<12} {m.name}{f'  ({m.note})' if m.note else ''}")


@models_app.command("download")
def models_download(
    whisper: str | None = typer.Option(
        None, "--whisper", help="faster-whisper model (default: the recommended one)."
    ),
    align: str = typer.Option("en", "--align", help="Alignment model language ('' to skip)."),
    diarization: bool = typer.Option(
        True, "--diarization/--no-diarization", help="Fetch the gated diarization model."
    ),
) -> None:
    """Pre-fetch models so that transcription can run offline (HF_HUB_OFFLINE=1)."""
    from meetingmaster3.errors import MM3Error
    from meetingmaster3.transcription import models

    missing = models.missing_engine_modules()
    if missing:
        typer.secho(f"Transcription engine not installed (missing: {', '.join(missing)}).",
                    fg=typer.colors.RED, err=True)  # fmt: skip
        typer.echo(models.INSTALL_HINT, err=True)
        raise typer.Exit(1)
    settings = load_settings()
    paths = resolve_paths()
    models.configure_model_cache(paths.models_dir, offline=False)
    if models.offline_mode():
        typer.secho("HF_HUB_OFFLINE is set; unset it to download.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    name = whisper or _recommended_whisper()
    typer.echo(f"Downloading whisper model {name} into {paths.models_dir} ...")
    typer.echo(f"  {models.download_whisper(name)}")
    if align:
        typer.echo(f"Downloading the alignment model for '{align}' ...")
        models.download_align(align)
    if diarization:
        model_id = settings.transcription.diarization_model
        typer.echo(f"Downloading the diarization model {model_id} ...")
        try:
            typer.echo(f"  {models.download_diarization(models.hf_token(settings), model_id)}")
        except MM3Error as exc:
            typer.secho(exc.message, fg=typer.colors.RED, err=True)
            typer.echo(exc.hint, err=True)
            raise typer.Exit(1) from exc
    typer.secho("Done.", fg=typer.colors.GREEN)


def main() -> None:
    app()
