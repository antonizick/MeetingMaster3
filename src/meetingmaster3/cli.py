"""The ``mm3`` command-line interface."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn

import typer
import uvicorn

from meetingmaster3 import __version__
from meetingmaster3.config.paths import resolve_paths
from meetingmaster3.config.settings import Settings, load_settings
from meetingmaster3.errors import MM3Error
from meetingmaster3.logging import configure_logging

if TYPE_CHECKING:
    from meetingmaster3.speakers.store import VoiceprintStore

app = typer.Typer(help="MeetingMaster3: local-first meeting intelligence.", no_args_is_help=True)
config_app = typer.Typer(help="Inspect configuration.", no_args_is_help=True)
app.add_typer(config_app, name="config")
llm_app = typer.Typer(help="Inspect LLM backends.", no_args_is_help=True)
app.add_typer(llm_app, name="llm")
jobs_app = typer.Typer(help="Inspect jobs and manage retained audio.", no_args_is_help=True)
app.add_typer(jobs_app, name="jobs")
models_app = typer.Typer(help="Download and inspect transcription models.", no_args_is_help=True)
app.add_typer(models_app, name="models")
templates_app = typer.Typer(help="List, validate and install note templates.", no_args_is_help=True)
app.add_typer(templates_app, name="templates")
voiceprints_app = typer.Typer(
    help="List or delete stored voices (opt-in speaker recognition).", no_args_is_help=True
)
app.add_typer(voiceprints_app, name="voiceprints")


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


def _voiceprint_store() -> VoiceprintStore:
    from meetingmaster3.speakers.store import VoiceprintStore
    from meetingmaster3.storage.db import Database

    paths = resolve_paths()
    paths.ensure()
    settings = load_settings()
    return VoiceprintStore(
        Database.open(paths.database), enabled=settings.privacy.voiceprints_enabled
    )


@voiceprints_app.command("list")
def voiceprints_list() -> None:
    """List stored voices: name, id, samples and when last seen (never the voice data)."""
    store = _voiceprint_store()
    try:
        people = store.list_people()
        state = "on" if store.enabled else "off"
        typer.echo(f"Voice recognition is {state}; {len(people)} stored voice(s).")
        for p in people:
            typer.echo(
                f"{p.person_id}  {p.n_samples:>3} sample(s)  {p.total_seconds / 60:5.1f} min  "
                f"last seen {p.updated_at[:10]}  {p.display_name}"
            )
    finally:
        store.db.close()


@voiceprints_app.command("delete")
def voiceprints_delete(person_id: str = typer.Argument(..., help="Id from `list`.")) -> None:
    """Delete one person's stored voice."""
    from meetingmaster3.errors import MM3Error

    store = _voiceprint_store()
    try:
        person = store.delete_person(person_id)
    except MM3Error as exc:
        typer.echo(f"{exc.message} {exc.hint}", err=True)
        raise typer.Exit(1) from exc
    finally:
        store.db.close()
    typer.echo(f"Deleted the stored voice of {person.display_name}.")


@voiceprints_app.command("wipe")
def voiceprints_wipe(
    yes: bool = typer.Option(False, "--yes", help="Do not ask for confirmation."),
) -> None:
    """Delete every stored voice (cannot be undone)."""
    store = _voiceprint_store()
    try:
        people = store.count_rows()["voiceprints"]
        if not yes and not typer.confirm(
            f"Delete every stored voice ({people} people)? This cannot be undone."
        ):
            typer.echo("Nothing deleted.")
            raise typer.Exit(1)
        counts = store.wipe()
    finally:
        store.db.close()
    typer.echo(
        f"Deleted {counts['voiceprints']} stored voice(s) and "
        f"{counts['voiceprint_embeddings']} sample(s)."
    )


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


# -- templates and headless processing (Phase 09) ------------------------------------------


def _library_settings(vault: str | None) -> Settings:
    settings = load_settings()
    if vault is not None:
        settings.vault.path = Path(vault)
    return settings


@templates_app.command("list")
def templates_list(
    vault: str | None = typer.Option(None, help="Vault folder (default from settings)."),
) -> None:
    """List the templates (vault copies override built-ins) and any invalid files."""
    from meetingmaster3.templates.stages import template_library

    settings = _library_settings(vault)
    library = template_library(settings)
    default = settings.generation.default_template
    for entry in library.listing():
        data = entry.to_dict()
        mark = "*" if data["id"] == default else " "
        state = "ok     " if entry.valid else "INVALID"
        origin = data["source"] + (" (overrides built-in)" if data["overrides_builtin"] else "")
        typer.echo(f"{mark} {state} {data['id'] or '?':<24} {data['name']:<28} {origin}")
        for issue in entry.all_issues:
            typer.echo(f"      {data['file']}: {issue}")
    typer.echo(f"(* = default: {default})")


@templates_app.command("validate")
def templates_validate(
    files: list[str] | None = typer.Argument(  # noqa: B008 - typer's declaration style
        None, help="Template files (default: the library)."
    ),
    vault: str | None = typer.Option(None, help="Vault folder (default from settings)."),
) -> None:
    """Check templates and report problems with line numbers. Exits 1 if any is invalid."""
    from meetingmaster3.templates.schema import parse_template_file
    from meetingmaster3.templates.stages import template_library

    bad = 0
    if files:
        for path in map(Path, files):
            report = parse_template_file(path)
            ok = report.ok
            bad += not ok
            typer.echo(f"{'ok     ' if ok else 'INVALID'} {path}")
            for issue in report.issues:
                typer.echo(f"  {path.name}:{issue.line}: {issue.message} [{issue.code}]")
    else:
        for entry in template_library(_library_settings(vault)).entries:
            bad += not entry.valid
            typer.echo(f"{'ok     ' if entry.valid else 'INVALID'} {entry.source:<7} {entry.path}")
            for issue in entry.all_issues:
                typer.echo(f"  {entry.path.name}:{issue.line}: {issue.message} [{issue.code}]")
    if bad:
        raise typer.Exit(1)


@templates_app.command("install")
def templates_install(
    vault: str | None = typer.Option(None, help="Vault folder (default from settings)."),
) -> None:
    """Copy the built-in templates into the vault (your edited copies are never replaced)."""
    from meetingmaster3.templates.loader import MANIFEST_NAME, install_builtins
    from meetingmaster3.vault.paths import resolve_vault_root

    settings = _library_settings(vault)
    paths = resolve_paths()
    paths.ensure()
    try:
        root = resolve_vault_root(settings.vault.path)
        results = install_builtins(
            root, settings.vault.templates_subfolder, paths.data_dir / MANIFEST_NAME
        )
    except MM3Error as exc:
        _fail(exc)
    for r in results:
        typer.echo(f"{r.action:<10} {settings.vault.templates_subfolder.rstrip('/')}/{r.file}")


def _fail(exc: MM3Error) -> NoReturn:
    typer.secho(f"Error: {exc.message}", fg=typer.colors.RED, err=True)
    if exc.hint:
        typer.echo(f"Hint: {exc.hint}", err=True)
    raise typer.Exit(1)


def _ask_on_tty(kind: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    """Answer a job question interactively (None when stdin is not a terminal)."""
    if not sys.stdin.isatty():
        return None
    if kind == "speaker_confirmation":
        typer.echo("Name the speakers (Enter keeps the suggestion or placeholder):")
        answer: dict[str, str] = {}
        for sp in payload.get("speakers", []):
            label = sp.get("label")
            suggestion = (sp.get("suggestion") or {}).get("name") or sp.get("placeholder") or label
            talk = sp.get("talk_seconds")
            extra = f" ({talk:.0f} s of speech)" if isinstance(talk, int | float) else ""
            answer[label] = typer.prompt(f"  {label}{extra}", default=suggestion)
        return {"speakers": answer}
    if kind == "cloud_consent":
        ok = typer.confirm(str(payload.get("message") or "Send the transcript to the cloud?"))
        return {"consent": ok}
    if kind == "language":
        typer.echo(str(payload.get("message", "The audio does not look like English.")))
        go = typer.confirm("Transcribe it in the detected language?", default=True)
        return {"action": "proceed" if go else "abort"}
    return None


@app.command()
def process(
    audio_file: str = typer.Argument(..., metavar="AUDIO", help="Recording to process."),
    title: str | None = typer.Option(None, help="Meeting title (default: from the file name)."),
    date: str | None = typer.Option(None, help="Meeting date, YYYY-MM-DD (default: file name)."),
    time: str | None = typer.Option(None, help="Meeting start time, HH:MM."),
    template: str | None = typer.Option(None, help="Template id (default from settings)."),
    backend: str | None = typer.Option(None, help="LLM backend name (default from settings)."),
    model: str | None = typer.Option(None, help="LLM model (default: the backend's)."),
    speakers: str | None = typer.Option(
        None, help='Speaker names, e.g. "SPEAKER_00=Alice,SPEAKER_01=Bob". Asked if omitted.'
    ),
    participants: str | None = typer.Option(None, help="Comma-separated extra participants."),
    tags: str | None = typer.Option(None, help="Comma-separated note tags."),
    location: str | None = typer.Option(None, help="Location or context."),
    instructions: str | None = typer.Option(None, help="Extra instructions for every section."),
    cloud_consent: bool = typer.Option(
        False, "--cloud-consent", help="Allow sending the transcript to a cloud backend."
    ),
    vault: str | None = typer.Option(None, help="Vault folder (default from settings)."),
    diarize: bool | None = typer.Option(None, "--diarize/--no-diarize", help="Separate speakers."),
    transcription_model: str | None = typer.Option(None, help="Whisper model override."),
    language: str | None = typer.Option(None, help="Force the spoken language (e.g. en)."),
) -> None:
    """Process a recording end to end: transcript, speaker names, notes, written to the vault."""
    audio = Path(audio_file)
    import asyncio
    import datetime as dt

    from meetingmaster3.headless import ProcessRequest, build_options, parse_speakers
    from meetingmaster3.headless import process as run_process
    from meetingmaster3.vault.paths import resolve_vault_root

    configure_logging()
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per LLM call is noise here
    settings = _library_settings(vault)
    paths = resolve_paths()

    def split(text: str | None) -> list[str]:
        return [p.strip() for p in (text or "").split(",") if p.strip()]

    try:
        resolve_vault_root(settings.vault.path)  # fail before transcribing for minutes
        try:
            day = dt.date.fromisoformat(date) if date else None
            start = dt.time.fromisoformat(time) if time else None
        except ValueError as exc:
            raise MM3Error("E_OPTIONS_INVALID", f"Invalid date or time: {exc}.", "") from exc
        options = build_options(
            audio,
            title=title,
            date=day,
            meeting_time=start,
            template=template,
            backend=backend,
            model=model,
            participants=split(participants),
            tags=split(tags),
            location=location,
            instructions=instructions,
            cloud_consent=cloud_consent,
            diarize=diarize,
            transcription_model=transcription_model,
            language=language,
        )
        request = ProcessRequest(
            audio, options, parse_speakers(speakers) if speakers else None, cloud_consent
        )
        result = asyncio.run(
            run_process(settings, paths, request, ask=_ask_on_tty, echo=typer.echo)
        )
    except MM3Error as exc:
        _fail(exc)
    except KeyboardInterrupt:
        typer.echo("Cancelled.", err=True)
        raise typer.Exit(130) from None
    for warning in result.warnings:
        typer.secho(f"Warning: {warning}", fg=typer.colors.YELLOW, err=True)
    if result.status.value != "written":
        err = result.error or {}
        _fail(MM3Error(err.get("code") or "E_JOB", err.get("message") or "", err.get("hint") or ""))
    w = result.written
    if w.get("note_path"):
        typer.secho(f"Note:       {w['note_path']}", fg=typer.colors.GREEN)
        if w.get("transcript_path"):
            typer.echo(f"Transcript: {w['transcript_path']}")
    else:
        typer.echo("Done (no vault configured; nothing was written).")


def main() -> None:
    app()
