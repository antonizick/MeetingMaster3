"""The ``generate`` and ``write`` job stages (spec §3 steps 4 and 8, R4, S6, Q2).

``generate`` turns the job's named transcript into ``notes.draft.md`` (a complete rendered note
without its transcript link). ``write`` puts the note and the companion transcript into the
vault, links them both ways, records the meeting in ``recent_meetings`` and returns
``written.json``. Both are safe to resume: ``generate`` keeps finished sections in
``generate.partial.json``, and ``write`` records its chosen file names in ``write.intent.json``
so a crash between the two files never produces a ``(2)`` duplicate.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from meetingmaster3.domain.meeting import UNTITLED, MeetingMeta
from meetingmaster3.domain.note import Section
from meetingmaster3.domain.transcript import SpeakerMap, Transcript
from meetingmaster3.errors import MM3Error
from meetingmaster3.jobs.models import JobOptions
from meetingmaster3.jobs.stage import BaseStage, InputRequired, StageContext
from meetingmaster3.llm.base import E_CONSENT_REQUIRED, E_LLM_CONFIG, LLMBackend, llm_error
from meetingmaster3.llm.consent import requires_consent
from meetingmaster3.markdown.note_parser import parse_note
from meetingmaster3.markdown.note_writer import build_note, render_note, with_transcript_link
from meetingmaster3.markdown.transcript_format import build_companion, render_transcript
from meetingmaster3.speakers.cascade import (
    NAMED_TRANSCRIPT_FILE,
    apply_speaker_map,
    load_job_speaker_map,
)
from meetingmaster3.templates.generator import NoteGenerator
from meetingmaster3.templates.loader import (
    MANIFEST_NAME,
    TemplateLibrary,
    ensure_installed,
    load_library,
)
from meetingmaster3.templates.schema import Template
from meetingmaster3.vault.io import atomic_write_text, read_text
from meetingmaster3.vault.naming import NotePaths, allocate_note_paths
from meetingmaster3.vault.paths import is_inside, output_folder, resolve_vault_root
from meetingmaster3.vault.readable import readable_link, write_readable

if TYPE_CHECKING:
    from meetingmaster3.config.settings import Settings

log = logging.getLogger(__name__)

DRAFT_FILE = "notes.draft.md"
PARTIAL_FILE = "generate.partial.json"
GENERATION_FILE = "generation.json"
WRITTEN_FILE = "written.json"
INTENT_FILE = "write.intent.json"
CONSENT_KIND = "cloud_consent"

BackendFactory = Callable[["Settings", str | None], tuple[str, LLMBackend]]
"""(settings, requested backend name) → (backend name, backend)."""


def registry_backend(settings: Settings, name: str | None) -> tuple[str, LLMBackend]:
    from meetingmaster3.llm.registry import BackendRegistry

    registry = BackendRegistry(settings)
    name = name or registry.default_name
    return name, registry.get(name)


def template_library(settings: Settings, data_dir: Path | None = None) -> TemplateLibrary:
    """Built-ins plus the vault's templates (installing the built-ins on first use; the
    install manifest lives in ``data_dir``, by default the app data folder)."""
    if settings.vault.path is None:
        return load_library()
    try:
        root = resolve_vault_root(settings.vault.path)
    except MM3Error:
        return load_library()
    if settings.generation.install_templates:
        from meetingmaster3.config.paths import resolve_paths

        try:
            ensure_installed(
                root,
                settings.vault.templates_subfolder,
                (data_dir or resolve_paths().data_dir) / MANIFEST_NAME,
            )
        except (MM3Error, OSError) as exc:
            log.warning("Could not install the starter templates: %s", exc)
    return load_library(root, settings.vault.templates_subfolder)


def resolve_model(settings: Settings, backend_name: str, requested: str | None) -> str:
    if requested:
        return requested
    cfg = settings.llm.backends.get(backend_name)
    if cfg is not None and cfg.default_model:
        return cfg.default_model
    raise llm_error(
        E_LLM_CONFIG,
        f"No model is chosen for the backend '{backend_name}'.",
        f"Pass a model (mm3 process --model, or the job's 'model' option), or set "
        f"llm.backends.{backend_name}.default_model in the configuration.",
        status_code=422,
    )


def meeting_datetime(options: JobOptions, created_at: dt.datetime) -> dt.datetime:
    """The meeting's date and time. Without a known time the result is midnight, which the
    note header shows as a date only."""
    day = options.meeting_date or created_at.astimezone().date()
    return dt.datetime.combine(day, options.meeting_time or dt.time(0))


def load_named_transcript(ctx: StageContext, speaker_map: SpeakerMap) -> Transcript:
    """The transcript with names (Phase 07's ``transcript.named.json``), or the diarized
    transcript with the speaker map applied."""
    named = ctx.job_dir / NAMED_TRANSCRIPT_FILE
    if named.is_file():
        return Transcript.model_validate_json(named.read_text(encoding="utf-8"))
    return speaker_map.apply(load_final_transcript(ctx))


def load_final_transcript(ctx: StageContext) -> Transcript:
    path = ctx.artifacts.get("diarize")
    if path is None or not path.is_file():
        raise MM3Error(
            "E_TRANSCRIPT_MISSING",
            "The transcript of this job is missing.",
            "Resume the job from the transcription stage, or upload the recording again.",
            status_code=409,
        )
    return Transcript.model_validate_json(path.read_text(encoding="utf-8"))


def _fingerprint(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:32]


class GenerateStage(BaseStage):
    name = "generate"
    display_name = "Generating notes"
    default_model: str | None = None
    """Model used when neither the job nor the backend config names one (fakes)."""

    def __init__(
        self,
        settings: Settings | None = None,
        backend_factory: BackendFactory | None = None,
        *,
        library_factory: Callable[[Settings], TemplateLibrary] | None = None,
        today: dt.date | None = None,
    ) -> None:
        super().__init__()
        self.settings = settings
        self.backend_factory = backend_factory or registry_backend
        self.library_factory = library_factory or template_library
        self.today = today
        self.uses_gpu = self.gpu_for({}) if settings is not None else False

    def gpu_for(self, options: dict[str, Any]) -> bool:
        """A local Ollama shares the GPU with transcription (R5), so the runner serialises the
        stage with other jobs' GPU stages."""
        if self.settings is None:
            return False
        try:
            _, backend = self.backend_factory(self.settings, options.get("backend"))
        except MM3Error:
            return False
        return backend.kind == "ollama" and backend.is_local

    # -- consent (S6) ------------------------------------------------------------------

    def validate_input(self, data: dict[str, Any]) -> dict[str, Any]:
        consent = data.get("consent")
        if not isinstance(consent, bool):
            raise MM3Error(
                "E_INPUT_INVALID",
                'Answer the cloud question with {"consent": true} or {"consent": false}.',
                "",
                status_code=422,
            )
        return {"consent": consent}

    def _check_consent(
        self, ctx: StageContext, options: JobOptions, name: str, backend: LLMBackend
    ) -> bool:
        """True when the job may send the transcript to ``backend``; pauses the job to ask
        otherwise."""
        from meetingmaster3.jobs.stage import input_path

        settings = ctx.settings
        # An answer is consumed by the run that reads it, whatever the outcome: a "yes" given
        # while the job was switched to a local model must never approve a cloud backend chosen
        # later (Phase 15 finding; S6).
        answer = ctx.input()
        input_path(ctx.job_dir, self.name).unlink(missing_ok=True)
        cfg = settings.llm.backends.get(name)
        remembered = bool(cfg and cfg.consent_remembered)
        if not requires_consent(backend) or remembered or options.cloud_consent_for == name:
            return True
        if options.cloud_consent:
            ctx.options["cloud_consent_for"] = name
            return True
        if answer is not None:
            if answer.get("consent") is True:
                ctx.options["cloud_consent_for"] = name
                return True
            raise llm_error(
                E_CONSENT_REQUIRED,
                f"Cloud use of '{name}' was declined, so no notes were generated.",
                "Resume the job with a local backend (for example Ollama), or confirm cloud use.",
                status_code=403,
            )
        raise InputRequired(
            CONSENT_KIND,
            {
                "backend": name,
                "backend_kind": backend.kind,
                "badge": f"cloud: {backend.kind}",
                "message": f"Generating the notes sends the transcript to '{name}' "
                f"({backend.kind}), a cloud service. Continue?",
            },
        )

    # -- run ---------------------------------------------------------------------------

    def build_meta(
        self, ctx: StageContext, options: JobOptions, template: Template, name: str, model: str
    ) -> MeetingMeta:
        return MeetingMeta(
            title=ctx.job.title or options.title or UNTITLED,
            date=meeting_datetime(options, ctx.job.created_at),
            participants=options.participants,
            tags=["meeting", *options.tags],
            location=options.location,
            template_id=template.id,
            backend=name,
            model=model,
            generated_at=dt.datetime.now().replace(microsecond=0),
        )

    def run(self, ctx: StageContext) -> Path:
        settings = ctx.settings
        options = JobOptions.model_validate(ctx.options)
        template_id = options.template or settings.generation.default_template
        template = self.library_factory(settings).get(template_id)
        name, backend = self.backend_factory(settings, options.backend)
        model = resolve_model(settings, name, options.model or self.default_model)
        consent = self._check_consent(ctx, options, name, backend)

        speaker_map = load_job_speaker_map(ctx.job_dir)
        final = load_final_transcript(ctx)
        named = load_named_transcript(ctx, speaker_map)
        meta = self.build_meta(ctx, options, template, name, model)
        meta = apply_speaker_map(speaker_map, final, meta=meta).meta or meta

        key = _fingerprint(
            template.model_dump_json(),
            name,
            model,
            options.instructions or "",
            named.model_dump_json(),
        )
        partial_path = ctx.artifact(PARTIAL_FILE)
        done: dict[str, str] = {}
        if partial_path.is_file():
            try:
                data = json.loads(partial_path.read_text(encoding="utf-8"))
                if data.get("key") == key:
                    done = {str(k): str(v) for k, v in data.get("sections", {}).items()}
            except ValueError:
                pass

        def checkpoint(section: Section) -> None:
            done[section.id] = section.body_markdown
            ctx.write_json(PARTIAL_FILE, {"key": key, "sections": done})

        reused = sorted(done)
        cfg = settings.llm.backends.get(name)
        generator = NoteGenerator(
            backend,
            model,
            template,
            cloud_consent=consent,
            consent_remembered=bool(cfg and cfg.consent_remembered),
            max_context=settings.generation.max_context,
            instructions=options.instructions,
            think=settings.generation.think,
            today=self.today,
            progress=lambda f, m: ctx.progress(f, m),
            check_cancelled=ctx.check_cancelled,
            warn=ctx.warn,
        )
        if self.gpu_for(ctx.options):
            from meetingmaster3.transcription.models import free_gpu_memory

            free_gpu_memory()
        result = asyncio.run(generator.generate(meta, named, done=done, on_section=checkpoint))
        note = build_note(meta, result.sections)
        path = ctx.artifact(DRAFT_FILE)
        atomic_write_text(path, render_note(note), overwrite=True)
        ctx.write_json(
            GENERATION_FILE,
            {
                "template": template.id,
                "backend": name,
                "model": model,
                "mode": result.mode,
                "chunks": result.chunks,
                "calls": result.calls,
                "reused_sections": reused,
            },
        )
        partial_path.unlink(missing_ok=True)
        return path


class WriteStage(BaseStage):
    name = "write"
    display_name = "Writing to vault"

    def _paths(self, ctx: StageContext, root: Path, meta: MeetingMeta) -> NotePaths:
        intent = ctx.artifact(INTENT_FILE)
        if intent.is_file():
            data = json.loads(intent.read_text(encoding="utf-8"))
            if data.get("mm3_id") == str(meta.id):
                folder = Path(data["folder"])
                if is_inside(root, folder):
                    folder.mkdir(parents=True, exist_ok=True)
                    return NotePaths(folder.resolve(), data["stem"])
        day = meta.date.date() if meta.date else dt.date.today()
        folder = output_folder(root, ctx.settings.vault.output_subfolder, day)
        paths = allocate_note_paths(folder, day, meta.title)
        ctx.write_json(
            INTENT_FILE, {"mm3_id": str(meta.id), "folder": str(folder), "stem": paths.stem}
        )
        return paths

    @staticmethod
    def _write(path: Path, text: str, root: Path, mm3_id: str) -> None:
        """Write a new file. A file already there from an earlier attempt of this job (same
        ``mm3-id``) is left as it is; anything else is never overwritten."""
        if path.exists():
            try:
                existing = read_text(path)
            except OSError:
                existing = ""
            if f"mm3-id: {mm3_id}" in existing:
                return
        atomic_write_text(path, text, vault_root=root)

    def run(self, ctx: StageContext) -> Path:
        settings = ctx.settings
        root = resolve_vault_root(settings.vault.path)
        parsed = parse_note(read_text(ctx.artifacts["generate"]))
        note = parsed.note
        paths = self._paths(ctx, root, note.meta)
        mm3_id = str(note.meta.id)
        companion = settings.generation.write_companion
        readable: Path | None = None

        if companion:
            speaker_map = load_job_speaker_map(ctx.job_dir)
            doc = build_companion(
                note.meta.id,
                note.meta.title,
                load_final_transcript(ctx),
                speaker_map,
                note_ref=paths.note_link,
            )
            self._write(paths.transcript, render_transcript(doc), root, mm3_id)
            if settings.generation.readable_transcript:
                try:
                    readable = write_readable(root, paths.note, doc, transcript=paths.transcript)
                except MM3Error as exc:
                    ctx.warn(f"The readable transcript was not written: {exc.message}")
        else:
            ctx.warn(
                "The companion transcript is turned off (generation.write_companion), so this "
                "note cannot be re-opened to regenerate sections or rename speakers."
            )
        meta = note.meta.model_copy(
            update={"transcript_ref": paths.transcript_link if companion else None}
        )
        note_text = render_note(note.with_meta(meta))
        if readable is not None:
            note_text = with_transcript_link(note_text, readable_link(readable))
        self._write(paths.note, note_text, root, mm3_id)

        if ctx.db is not None:
            from meetingmaster3.storage.repositories import RecentMeetingsRepository

            RecentMeetingsRepository(ctx.db).touch(
                str(paths.note),
                transcript_path=str(paths.transcript) if companion else None,
                mm3_id=mm3_id,
                title=meta.title,
                date=meta.date.date() if meta.date else None,
                job_id=ctx.job_id,
            )
        return ctx.write_json(
            WRITTEN_FILE,
            {
                "mm3_id": mm3_id,
                "vault_root": str(root),
                "note_path": str(paths.note),
                "note_relative": paths.note.relative_to(root).as_posix(),
                "transcript_path": str(paths.transcript) if companion else None,
                "transcript_relative": paths.transcript.relative_to(root).as_posix()
                if companion
                else None,
                "readable_relative": readable.relative_to(root).as_posix() if readable else None,
                "title": meta.title,
                "template": meta.template_id,
            },
        )
