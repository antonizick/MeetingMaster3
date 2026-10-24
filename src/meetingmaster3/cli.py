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
notes_app = typer.Typer(help="Bring notes in the vault up to date.", no_args_is_help=True)
app.add_typer(notes_app, name="notes")
meetings_app = typer.Typer(help="Rename and re-date meetings.", no_args_is_help=True)
app.add_typer(meetings_app, name="meetings")


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
            log_config=None,
        )
    else:
        from meetingmaster3.app import create_app

        uvicorn.run(
            create_app(settings),
            host=settings.server.host,
            port=settings.server.port,
            log_config=None,  # uvicorn's own handlers write to the terminal synchronously
        )


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
        counts = store.wipe(resolve_paths().jobs_dir)
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


@notes_app.command("upgrade")
def notes_upgrade(
    dry_run: bool = typer.Option(False, "--dry-run", help="Show the plan; write nothing."),
    note: str | None = typer.Option(None, "--note", help="Only this note (vault-relative)."),
    backend: str | None = typer.Option(None, help="LLM backend (default from settings)."),
    model: str | None = typer.Option(None, help="Model (default: the backend's default)."),
    allow_cloud: bool = typer.Option(
        False, "--allow-cloud", help="Agree to send transcripts to a cloud backend."
    ),
    vault: str | None = typer.Option(None, help="Vault folder (default from settings)."),
) -> None:
    """Add Summary Detailed, rename "Summary" to "Summary Succinct" and write readable
    transcripts for notes made before Phase 15a. Each changed note is archived first."""
    import asyncio

    from meetingmaster3.llm.registry import BackendRegistry
    from meetingmaster3.review.upgrade import apply_note, choose_model, plan_vault
    from meetingmaster3.templates.loader import MANIFEST_NAME, planning_library
    from meetingmaster3.vault.paths import confine, resolve_vault_root

    configure_logging()
    settings = _library_settings(vault)
    try:
        root = resolve_vault_root(settings.vault.path)
        only = confine(root, note) if note is not None else None
        manifest = resolve_paths().data_dir / MANIFEST_NAME
        library = planning_library(root, settings.vault.templates_subfolder, manifest)
        plan = plan_vault(root, library, settings, only=only)
    except MM3Error as exc:
        _fail(exc)
    counts = plan.counts()
    typer.echo(
        f"{counts['notes']} MM3 notes: {counts['todo']} to update, "
        f"{counts['up_to_date']} up to date, {counts['skipped']} skipped."
    )
    for n in plan.todo:
        typer.echo(f"  update  {n.rel}: {'; '.join(n.changes)}")
    for n in plan.skipped:
        typer.echo(f"  skip    {n.rel}: {n.skip}")
    if not plan.todo:
        return

    async def run() -> int:
        choice = None
        if any(n.needs_model for n in plan.todo):
            choice = await choose_model(BackendRegistry(settings), settings, backend, model)
            typer.echo(
                f"Model: {choice.backend_name} · {choice.model}"
                f"{' (cloud)' if choice.cloud else ' (local)'}; "
                f"estimated {max(1, round(plan.estimate_seconds() / 60))} min."
            )
            if choice.cloud and not allow_cloud and not dry_run:
                raise MM3Error(
                    "E_CONSENT_REQUIRED",
                    f"This sends the notes' transcripts to {choice.backend_name}, a cloud service.",
                    "Pass --allow-cloud to agree, or choose a local model with --backend/--model.",
                )
        if dry_run:
            typer.echo("Dry run: nothing was written.")
            return 0
        failed = 0
        for n in plan.todo:
            r = await apply_note(
                root,
                n,
                library=library,
                settings=settings,
                backend=choice.backend if choice else None,
                backend_name=choice.backend_name if choice else "",
                model=choice.model if choice else "",
                cloud_consent=allow_cloud,
            )
            failed += r.status == "failed"
            extra = f" (archived as {r.archive})" if r.archive else ""
            typer.echo(f"  {r.status:<9} {r.rel}{extra}{': ' + r.message if r.message else ''}")
            for w in r.warnings:
                typer.echo(f"    warning: {w}")
        return 1 if failed else 0

    try:
        code = asyncio.run(run())
    except MM3Error as exc:
        _fail(exc)
    raise typer.Exit(code)


@notes_app.command("relink")
def notes_relink(
    dry_run: bool = typer.Option(False, "--dry-run", help="Show the plan; change nothing."),
    vault: str | None = typer.Option(None, help="Vault folder (default from settings)."),
) -> None:
    """Re-link Meetings entries whose notes moved, by each note's ``mm3-id``.

    Only the Meetings list is updated; no note file is touched. Entries with no match, or with
    several, are listed and left alone (choose those on the Meetings page)."""
    from meetingmaster3.storage.db import Database
    from meetingmaster3.storage.repositories import RecentMeetingsRepository
    from meetingmaster3.vault import relink
    from meetingmaster3.vault.paths import resolve_vault_root

    configure_logging()
    settings = _library_settings(vault)
    paths = resolve_paths()
    paths.ensure()
    try:
        root = resolve_vault_root(settings.vault.path)
        db = Database.open(paths.database)
        try:
            repo = RecentMeetingsRepository(db)
            matches = relink.plan_relink(root, repo.recent(10_000))
            if not matches:
                typer.echo("Every Meetings entry still points to a note in the vault.")
                return
            for m in matches:
                label = m.entry.title or m.entry.note_path
                if m.status == "found":
                    typer.echo(f"  link       {label} -> {m.candidates[0].rel(root)}")
                elif m.status == "ambiguous":
                    typer.echo(f"  ambiguous  {label}: {len(m.candidates)} notes match")
                else:
                    typer.echo(f"  not found  {label}")
            if dry_run:
                typer.echo("Dry run: nothing was changed.")
                return
            done = relink.apply_clear_matches(repo, matches)
            typer.echo(f"Re-linked {done} of {len(matches)} entries.")
        finally:
            db.close()
    except MM3Error as exc:
        _fail(exc)


def _find_note(root: Path, target: str, data_dir: Path) -> Path:
    """A meeting's note from its ``mm3-id`` (Meetings list, else a vault search) or its
    vault-relative path."""
    import os
    import uuid

    from meetingmaster3.review.workspace import locate_note
    from meetingmaster3.storage.db import Database
    from meetingmaster3.storage.repositories import RecentMeetingsRepository
    from meetingmaster3.vault.paths import confine
    from meetingmaster3.vault.picker import read_identity

    try:
        mm3_id = str(uuid.UUID(target))
    except ValueError:
        return confine(root, target)
    db = Database.open(data_dir / "mm3.db")
    try:
        return locate_note(root, RecentMeetingsRepository(db), mm3_id)[0]
    except MM3Error:
        pass
    finally:
        db.close()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if name.endswith(".md"):
                info = read_identity(Path(dirpath) / name)
                if info is not None and info.is_note and info.mm3_id == mm3_id:
                    return Path(dirpath) / name
    raise MM3Error("E_NOTE_NOT_FOUND", f"No note with mm3-id {mm3_id} is in the vault.", "")


@meetings_app.command("rename")
def meetings_rename(
    target: str = typer.Argument(..., help="The meeting's mm3-id, or its note (vault-relative)."),
    title: str | None = typer.Option(None, "--title", help="The new title."),
    date: str | None = typer.Option(None, "--date", help="The new date, YYYY-MM-DD."),
    time: str | None = typer.Option(
        None, "--time", help="The new time, HH:MM, or 'none' for unknown (default: keep it)."
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show the plan; write nothing."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Apply without asking."),
    vault: str | None = typer.Option(None, help="Vault folder (default from settings)."),
) -> None:
    """Change a meeting's title and/or date everywhere: its files, their links in other notes
    (backed up first) and the database. The same operation as "Title & date…" on the review page."""
    import datetime as dt

    from meetingmaster3.review.retitle import KEEP, apply_retitle, plan_retitle, recover_renames
    from meetingmaster3.review.store import ReviewStore
    from meetingmaster3.storage.db import Database
    from meetingmaster3.vault.io import read_text
    from meetingmaster3.vault.paths import resolve_vault_root

    configure_logging()
    settings = _library_settings(vault)
    paths = resolve_paths()
    paths.ensure()
    try:
        new_date = dt.date.fromisoformat(date) if date else None
        new_time: Any = KEEP
        if time is not None:
            new_time = None if time.strip().lower() in ("", "none") else dt.time.fromisoformat(time)
    except ValueError as exc:
        _fail(
            MM3Error("E_RETITLE_INVALID", f"Not a date or time: {exc}.", "Use YYYY-MM-DD, HH:MM.")
        )
    if title is None and date is None and time is None:
        _fail(
            MM3Error("E_RETITLE_NOTHING", "Nothing to change.", "Give --title, --date or --time.")
        )
    db = Database.open(paths.database)
    try:
        for r in recover_renames(paths.data_dir, db, paths.jobs_dir):
            typer.echo(r.message)
        root = resolve_vault_root(settings.vault.path)
        note = _find_note(root, target, paths.data_dir)
        plan = plan_retitle(
            root,
            note,
            title=title,
            date=new_date,
            time=new_time,
            output_subfolder=settings.vault.output_subfolder,
        )
        d = plan.to_dict()
        typer.echo(f"Meeting {plan.mm3_id}")
        typer.echo(f"  title: {plan.old_title!r} -> {plan.new_title!r}")
        typer.echo(f"  date:  {d['old_date']} -> {d['new_date']}")
        if plan.old_folder != plan.new_folder:
            typer.echo(f"  folder: {plan.old_folder} -> {plan.new_folder}")
        for f in plan.files:
            typer.echo(
                f"  {f.role:<9} {f.old_rel}" + (f"\n            -> {f.new_rel}" if f.moved else "")
            )
            for c in f.changes:
                typer.echo(f"            {c.label}: {c.before!r} -> {c.after!r}")
        typer.echo(
            f"  links: {plan.link_count} in {len(plan.links)} other note(s)"
            f" ({plan.scanned} searched)"
        )
        for f in plan.links:
            typer.echo(f"  link      {f.old_rel}")
            for c in f.changes:
                typer.echo(f"            {c.label}: {c.before} -> {c.after}")
        for w in plan.warnings:
            typer.echo(f"  warning: {w}")
        for b in plan.blocked:
            typer.secho(f"  blocked: {b}", fg=typer.colors.RED)
        if plan.blocked:
            raise typer.Exit(1)
        if plan.empty:
            typer.echo("Nothing to change.")
            return
        if dry_run:
            typer.echo("Dry run: nothing was written.")
            return
        if not yes and not typer.confirm("Apply this rename?"):
            raise typer.Exit(1)
        result = apply_retitle(plan, data_dir=paths.data_dir, db=db, jobs_root=paths.jobs_dir)
        ReviewStore(paths.data_dir, plan.mm3_id).put_base(read_text(root / result.note_rel))
    except MM3Error as exc:
        _fail(exc)
    finally:
        db.close()
    typer.secho(f"Renamed: {result.note_rel}", fg=typer.colors.GREEN)
    typer.echo(f"Backups and manifest: {result.backup}")
    for w in result.warnings:
        typer.echo(f"  warning: {w}")


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
    if kind == "import_confirmation":
        name = payload.get("format_name") or "the file"
        typer.echo(f"Read {payload.get('turns', 0)} turns from {name}.")
        low = payload.get("low_confidence") or 0
        if low:
            typer.echo(
                f"{low} turn(s) were guessed with low confidence; check them in the web app "
                "if the speakers matter."
            )
        typer.echo("Name the speakers (Enter keeps the name shown):")
        names: dict[str, str] = {}
        for sp in payload.get("speakers", []):
            label = sp.get("label")
            role = f" ({sp['role']})" if sp.get("role") in ("user", "assistant") else ""
            names[label] = typer.prompt(f"  {label}{role}", default=sp.get("default_name") or label)
        return {"speakers": names, "turns": {}}
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
    _report(result)


def _report(result: Any) -> None:
    """Print the outcome of ``mm3 process`` / ``mm3 import`` (exit 1 unless written)."""
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


@app.command("import")
def import_file(
    source: str = typer.Argument(
        ..., metavar="FILE|LINK", help="Transcript or AI conversation file, or a Grok share link."
    ),
    title: str | None = typer.Option(
        None, help="Title (default: the file's heading, else its name)."
    ),
    date: str | None = typer.Option(None, help="Date, YYYY-MM-DD (default: file, else today)."),
    time: str | None = typer.Option(None, help="Start time, HH:MM."),
    template: str | None = typer.Option(None, help="Template id (default from settings)."),
    backend: str | None = typer.Option(None, help="LLM backend name (default from settings)."),
    model: str | None = typer.Option(None, help="LLM model (default: the backend's)."),
    speaker: list[str] = typer.Option(  # noqa: B008
        [],
        "--speaker",
        help="A speaker's name: user=Nick, assistant=Grok or SPEAKER_00=Alice (repeatable).",
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Accept the detected speakers without asking."
    ),
    participants: str | None = typer.Option(None, help="Comma-separated participants."),
    tags: str | None = typer.Option(None, help="Comma-separated note tags."),
    location: str | None = typer.Option(None, help="Location or context."),
    instructions: str | None = typer.Option(None, help="Extra instructions for every section."),
    cloud_consent: bool = typer.Option(
        False, "--cloud-consent", help="Allow sending the text to a cloud backend."
    ),
    vault: str | None = typer.Option(None, help="Vault folder (default from settings)."),
) -> None:
    """Import a transcript or an AI conversation (Markdown chat export, [hh:mm:ss] Name: text,
    MeetingMaster3 .transcript.md, .vtt, .srt, or a Grok share link, which is downloaded from
    grok.com) and write its notes to the vault, like a meeting. No audio and no transcription."""
    import asyncio
    import datetime as dt
    import functools

    from meetingmaster3.headless import (
        ProcessRequest,
        build_import_options,
        build_share_options,
        parse_speakers,
    )
    from meetingmaster3.headless import process as run_process
    from meetingmaster3.importing.grok_share import looks_like_share_url
    from meetingmaster3.importing.stages import CONFIRMED_OPTION, SPEAKERS_OPTION
    from meetingmaster3.vault.paths import resolve_vault_root

    configure_logging()
    logging.getLogger("httpx").setLevel(logging.WARNING)
    settings = _library_settings(vault)
    paths = resolve_paths()
    path = Path(source)

    def split(text: str | None) -> list[str]:
        return [p.strip() for p in (text or "").split(",") if p.strip()]

    try:
        resolve_vault_root(settings.vault.path)
        share = not path.is_file() and looks_like_share_url(source)
        if not share and not path.is_file():
            raise MM3Error("E_IMPORT_MISSING", f"No file at {source!r}.", "")
        try:
            day = dt.date.fromisoformat(date) if date else None
            start = dt.time.fromisoformat(time) if time else None
        except ValueError as exc:
            raise MM3Error("E_OPTIONS_INVALID", f"Invalid date or time: {exc}.", "") from exc
        names = parse_speakers(",".join(speaker)) if speaker else {}
        build = (
            functools.partial(build_share_options, source)
            if share
            else functools.partial(build_import_options, path, path.read_bytes(), settings)
        )
        options = build(
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
            **{SPEAKERS_OPTION: names, CONFIRMED_OPTION: yes or None},
        )
        request = ProcessRequest(path, options, None, cloud_consent, job_type="import", share=share)
        result = asyncio.run(
            run_process(settings, paths, request, ask=_ask_on_tty, echo=typer.echo)
        )
    except MM3Error as exc:
        _fail(exc)
    except KeyboardInterrupt:
        typer.echo("Cancelled.", err=True)
        raise typer.Exit(130) from None
    _report(result)


# -- search (Phase 15i) ------------------------------------------------------------------------


def _search_service(settings: Settings) -> Any:
    """The same service as the server's, gated on ``mm3.db`` instead of the runner (a server may
    be transcribing at the same time)."""
    from meetingmaster3.llm.registry import BackendRegistry
    from meetingmaster3.search.service import JobsTableGate, SearchService

    paths = resolve_paths()
    paths.ensure()
    registry = BackendRegistry(settings)
    return SearchService(
        settings, paths, registry.names, registry.get, JobsTableGate(paths.database)
    )


async def _search_index(settings: Settings, rebuild: bool) -> None:
    import asyncio

    service = _search_service(settings)
    try:
        task = service.start_update(rebuild=rebuild)
        last = ""
        while task.runner is not None and not task.runner.done():
            if task.message != last:
                last = task.message
                typer.echo(f"  {task.message}", err=True)
            await asyncio.sleep(0.5)
        if task.error is not None:
            _fail(task.error)
        r = service.last_report
        if r is not None:
            typer.echo(
                f"Indexed in {r.seconds:.1f} s: {r.added} added, {r.updated} updated, {r.moved} "
                f"moved, {r.removed} removed, {r.unchanged} unchanged; {r.embedded} passages "
                f"embedded ({r.embed_seconds:.1f} s)."
            )
            for path, message in r.failed:
                typer.secho(f"  not indexed: {path}: {message}", fg=typer.colors.YELLOW)
            if r.vector_error is not None:
                typer.secho(
                    f"Words only: {r.vector_error.message}", fg=typer.colors.YELLOW, err=True
                )
                if r.vector_error.hint:
                    typer.echo(f"Hint: {r.vector_error.hint}", err=True)
        if not settings.search.enabled:
            typer.echo("Note: search.enabled is off, so the server does not keep this up to date.")
    finally:
        await service.stop()


def _print_status(settings: Settings) -> None:
    import asyncio

    service = _search_service(settings)
    try:
        st = service.status()
    finally:
        asyncio.run(service.stop())
    emb = st["embedder"]
    typer.echo(f"Index:     {st['path']}{'' if st['exists'] else ' (not built)'}")
    typer.echo(f"Enabled:   {'yes' if st['enabled'] else 'no'}")
    if "error" in emb:
        typer.echo(f"Embedder:  unavailable: {emb['error']} {emb.get('hint', '')}".rstrip())
    else:
        allowed = "" if emb["consented"] else " (not allowed to index: no consent)"
        typer.echo(f"Embedder:  {emb['model']} on {emb['backend']} ({emb['badge']}){allowed}")
    typer.echo(
        f"Meetings:  {st['meetings']} ({st['notes']} notes, {st['transcripts']} transcripts)"
    )
    typer.echo(f"Passages:  {st['passages']}, {st['vectors']} with vectors")
    typer.echo(f"Size:      {st['size_bytes'] / 1048576:.1f} MB")
    typer.echo(f"Updated:   {st['last_update'] or 'never'}")
    if st["vector_error"]:
        typer.secho(f"Words only: {st['vector_error']}", fg=typer.colors.YELLOW)


@app.command("search")
def search(
    words: list[str] = typer.Argument(  # noqa: B008 - typer's declaration style
        None,
        help='What to look for, in your own words. Or "index" (update the index) or "status".',
    ),
    query: str | None = typer.Option(
        None, "--query", "-q", help='Search for this text (use it to search for "index").'
    ),
    limit: int = typer.Option(10, help="How many meetings to list."),
    date_from: str | None = typer.Option(None, "--from", help="Only meetings on or after."),
    date_to: str | None = typer.Option(None, "--to", help="Only meetings on or before."),
    person: list[str] = typer.Option(  # noqa: B008
        None, "--person", help="Only meetings with this participant or speaker (repeatable)."
    ),
    as_json: bool = typer.Option(False, "--json", help="Print the result as JSON."),
    rebuild: bool = typer.Option(False, "--rebuild", help="With index: start from scratch."),
) -> None:
    """Search the meetings by meaning and by words (`mm3 search "<question>"`), update the
    index (`mm3 search index [--rebuild]`) or show it (`mm3 search status`)."""
    import asyncio
    import datetime as dt
    import json

    from meetingmaster3.search.query import SearchFilters

    configure_logging()
    settings = load_settings()
    words = list(words or [])
    if query is None and words == ["index"]:
        asyncio.run(_search_index(settings, rebuild))
        return
    if query is None and words == ["status"]:
        _print_status(settings)
        return
    text = query if query is not None else " ".join(words)
    if not text.strip():
        typer.secho('Give some words to search for, e.g. mm3 search "budget".', err=True)
        raise typer.Exit(2)
    try:
        filters = SearchFilters(
            date_from=dt.date.fromisoformat(date_from).isoformat() if date_from else None,
            date_to=dt.date.fromisoformat(date_to).isoformat() if date_to else None,
            people=tuple(person or ()),
        )
    except ValueError:
        _fail(MM3Error("E_BAD_DATE", "--from and --to take a date like 2026-10-22.", ""))

    async def run() -> Any:
        service = _search_service(settings)
        try:
            return await service.query(text, limit=max(30, limit * 5), filters=filters)
        finally:
            await service.stop()

    try:
        result = asyncio.run(run())
    except MM3Error as exc:
        _fail(exc)
    meetings = result.group_by_meeting()[:limit]
    if as_json:
        data = result.to_dict()
        data["meetings"] = [m.to_dict() for m in meetings]
        typer.echo(json.dumps(data, indent=2, ensure_ascii=False))
        return
    mode = {"hybrid": "meaning + words", "meaning": "meaning", "words": "words only"}
    typer.echo(f"{len(meetings)} meeting(s), {mode.get(result.mode, 'nothing searched')}.")
    if result.reason:
        typer.secho(result.reason, fg=typer.colors.YELLOW, err=True)
    for m in meetings:
        typer.secho(f"\n{m.date or '----------'}  {m.title}", bold=True)
        typer.echo(f"            {m.note_path or '(no note)'}  [{m.mm3_id}]")
        for h in m.hits[:3]:
            typer.echo(f"  - {h.label()}: {h.snippet_text()}")


# -- ask (Phase 15j) ---------------------------------------------------------------------------


def _ask_json(result: Any, record: Any) -> dict[str, Any]:
    t = result.trace
    return {
        "question": result.question,
        "answer": result.answer,
        "count": result.count,
        "meetings": [
            {
                "mm3_id": r.mm3_id,
                "title": r.title,
                "date": r.date,
                "note_path": r.note_path,
                "link": f"[[{r.stem}]]",
                "relevance": r.relevance,
                "attendees": list(r.attendees),
                "took_part": list(r.spoke),
                "roles": dict(r.roles),
            }
            for r in result.rows
        ],
        "people": [
            {"name": p.name, "meetings": p.meetings, "roles": list(p.roles)} for p in result.people
        ],
        "backend": result.backend,
        "model": result.model,
        "trace": {
            "queries": [q for plan in t.plans for q in plan.queries],
            "read": t.read,
            "candidates": t.candidates,
            "follow_up": t.follow_up,
            "removed_links": t.stripped,
            "calls": t.calls,
            "input_tokens": t.input_tokens,
            "output_tokens": t.output_tokens,
            "seconds": round(t.seconds, 1),
        },
        "saved": record.vault_path if record is not None else None,
        "answer_id": record.id if record is not None else None,
    }


@app.command("ask")
def ask(
    words: list[str] = typer.Argument(  # noqa: B008 - typer's declaration style
        None, help="Your question about the meetings, in your own words."
    ),
    backend: str | None = typer.Option(None, help="Backend that answers (default: Settings)."),
    model: str | None = typer.Option(None, help="Model that answers (default: Settings)."),
    date_from: str | None = typer.Option(None, "--from", help="Only meetings on or after."),
    date_to: str | None = typer.Option(None, "--to", help="Only meetings on or before."),
    person: str | None = typer.Option(None, "--person", help="Only meetings with this person."),
    allow_cloud: bool = typer.Option(
        False,
        "--allow-cloud",
        help="Allow a cloud backend to receive meeting excerpts for this question.",
    ),
    no_save: bool = typer.Option(False, "--no-save", help="Do not save the answer note."),
    as_json: bool = typer.Option(False, "--json", help="Print the result as JSON."),
) -> None:
    """Answer a broad question from the meetings on file (`mm3 ask "<question>"`): searches the
    index, reads each matching meeting with the model and prints a cited answer with a table of
    the meetings, dates and attendees, saved as a note in the vault's answers folder."""
    import asyncio
    import datetime as dt
    import json

    from meetingmaster3.ask.notes import render_people, render_table
    from meetingmaster3.ask.service import AskService
    from meetingmaster3.llm.registry import BackendRegistry
    from meetingmaster3.search.query import SearchFilters
    from meetingmaster3.search.service import JobsTableGate
    from meetingmaster3.storage.db import Database

    configure_logging()
    settings = load_settings()
    question = " ".join(words or []).strip()
    if not question:
        typer.secho('Give a question, e.g. mm3 ask "who discussed the budget?"', err=True)
        raise typer.Exit(2)
    try:
        filters = SearchFilters(
            date_from=dt.date.fromisoformat(date_from).isoformat() if date_from else None,
            date_to=dt.date.fromisoformat(date_to).isoformat() if date_to else None,
            people=(person,) if person else (),
        )
    except ValueError:
        _fail(MM3Error("E_BAD_DATE", "--from and --to take a date like 2026-10-22.", ""))

    def progress(fraction: float, message: str) -> None:
        if not as_json:
            typer.echo(f"  {message}", err=True)

    async def run() -> Any:
        paths = resolve_paths()
        search = _search_service(settings)
        db = Database.open(paths.database)
        registry = BackendRegistry(settings)
        service = AskService(
            settings, db, search, registry.get, registry.names, JobsTableGate(paths.database)
        )
        try:
            return await service.ask(
                question,
                backend=backend,
                model=model,
                cloud_consent=allow_cloud,
                filters=filters,
                save=False if no_save else None,
                progress=progress,
            )
        finally:
            await search.stop()
            db.close()

    try:
        result, record = asyncio.run(run())
    except MM3Error as exc:
        _fail(exc)
    if as_json:
        typer.echo(json.dumps(_ask_json(result, record), indent=2, ensure_ascii=False))
        return
    typer.echo("")
    typer.echo(result.answer)
    if result.rows:
        typer.echo("")
        typer.echo(render_table(result.rows))
    if result.people:
        typer.echo("")
        typer.echo(render_people(result.people))
    t = result.trace
    typer.echo("")
    typer.echo(
        f"{t.read} meeting(s) read, {result.count} relevant · {result.model} on "
        f"{result.backend} · {t.seconds:.0f} s",
        err=True,
    )
    if record is not None:
        typer.secho(f"Saved: {record.vault_path}", fg=typer.colors.GREEN)
    elif not no_save and not settings.ask.keep_history:
        typer.echo("Not saved (ask.keep_history is off).", err=True)


def main() -> None:
    app()
