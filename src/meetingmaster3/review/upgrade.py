"""Bring older MM3 notes up to date ("Update older notes", ``mm3 notes upgrade``; R25, ADR-0031).

For every live MM3 note in the vault, :func:`plan_note` works out (without writing anything):

* the summary sections its template now has and the note lacks (``summary-detailed``, and
  ``summary`` for the templates that gained both), generated from the companion transcript;
* renaming the ``summary`` heading to "Summary Succinct", only while it is still the default
  "Summary" (a heading the user changed wins);
* the readable transcript, when it is missing (and the setting is on).

:func:`apply_note` then generates the new sections with the regeneration path, inserts them
after their neighbours in the template, archives the previous version of the note, and writes
the note atomically after checking that its ``mm3-id`` and SHA-256 did not change while the model
was working (an edit made in Obsidian during the run is never overwritten). Applying a note that
is already up to date changes nothing.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import os
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from meetingmaster3.config.settings import Settings
from meetingmaster3.domain.note import Section
from meetingmaster3.errors import MM3Error
from meetingmaster3.llm.base import LLMBackend
from meetingmaster3.llm.consent import requires_consent
from meetingmaster3.llm.registry import BackendRegistry
from meetingmaster3.markdown.note_parser import ParsedNote, parse_note
from meetingmaster3.markdown.note_writer import header_transcript_line, with_transcript_link
from meetingmaster3.markdown.sections import insert_section, rename_heading, scan_sections
from meetingmaster3.review.store import text_sha
from meetingmaster3.templates.generator import NoteGenerator
from meetingmaster3.templates.loader import TemplateLibrary
from meetingmaster3.templates.model_check import model_problem, suggest
from meetingmaster3.templates.regenerate import find_companion
from meetingmaster3.templates.schema import Template
from meetingmaster3.vault.archive import ARCHIVE_FOLDER, archive_note
from meetingmaster3.vault.io import atomic_write_text, read_text
from meetingmaster3.vault.naming import NOTE_SUFFIX, TRANSCRIPT_SUFFIX
from meetingmaster3.vault.paths import is_inside
from meetingmaster3.vault.picker import read_identity
from meetingmaster3.vault.readable import find_readable, readable_link, write_readable

log = logging.getLogger(__name__)

SUMMARY_IDS = ("summary", "summary-detailed")
OLD_HEADING = "Summary"
NEW_HEADING = "Summary Succinct"
MAX_NOTES = 20000
"""Markdown files examined per scan, like the picker's "locate" limit."""

E_NOTE_CHANGED = "E_NOTE_CHANGED"


@dataclass(frozen=True)
class NotePlan:
    path: Path
    rel: str
    mm3_id: str
    title: str
    date: str | None
    sha: str
    add_sections: tuple[str, ...] = ()
    rename_heading: bool = False
    write_readable: bool = False
    skip: str | None = None
    """Why the note cannot be upgraded (no companion transcript, damaged markers...)."""
    duration: float | None = None
    """Seconds of the meeting, from the companion transcript (for the time estimate)."""

    @property
    def changes(self) -> list[str]:
        out = []
        if self.add_sections:
            titles = {"summary": "Summary Succinct", "summary-detailed": "Summary Detailed"}
            out.append("add " + " and ".join(titles.get(s, s) for s in self.add_sections))
        if self.rename_heading:
            out.append('rename "Summary" to "Summary Succinct"')
        if self.write_readable:
            out.append("write the readable transcript")
        return out

    @property
    def needed(self) -> bool:
        return self.skip is None and bool(self.changes)

    @property
    def needs_model(self) -> bool:
        return self.skip is None and bool(self.add_sections)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["path"] = str(self.path)
        data.update(changes=self.changes, needed=self.needed, needs_model=self.needs_model)
        return data


@dataclass(frozen=True)
class UpgradePlan:
    notes: tuple[NotePlan, ...]

    @property
    def todo(self) -> list[NotePlan]:
        return [n for n in self.notes if n.needed]

    @property
    def skipped(self) -> list[NotePlan]:
        return [n for n in self.notes if n.skip is not None]

    def estimate_seconds(self) -> int:
        return sum(estimate_note_seconds(n) for n in self.todo)

    def counts(self) -> dict[str, int]:
        todo = self.todo
        return {
            "notes": len(self.notes),
            "todo": len(todo),
            "add_sections": sum(bool(n.add_sections) for n in todo),
            "rename_heading": sum(n.rename_heading for n in todo),
            "write_readable": sum(n.write_readable for n in todo),
            "needs_model": sum(n.needs_model for n in todo),
            "skipped": len(self.skipped),
            "up_to_date": len(self.notes) - len(todo) - len(self.skipped),
        }


@dataclass
class NoteResult:
    rel: str
    status: str
    """``updated``, ``unchanged``, ``skipped`` or ``failed``."""
    message: str = ""
    archive: str | None = None
    readable: str | None = None
    added: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


FULL_CONTEXT_MINUTES = 40.0
"""Meetings longer than this go through map-reduce with the default 16k context on 8 GB."""
EXTRA_SECTION_SECONDS = 25.0


def estimate_note_seconds(plan: NotePlan) -> int:
    """qwen3:8b on the 8 GB reference GPU (Phase 15a, docs/PERFORMANCE.md): the first new section
    costs reading the whole transcript (31 min: 66 s); a long meeting is read again through
    map-reduce (72 min: 317 s). Further sections of the same note reuse that context."""
    if not plan.needs_model:
        return 1
    minutes = (plan.duration or 1800.0) / 60
    first = 15 + 1.7 * minutes if minutes <= FULL_CONTEXT_MINUTES else 4.4 * minutes
    return round(first + EXTRA_SECTION_SECONDS * (len(plan.add_sections) - 1))


# -- scanning and planning ---------------------------------------------------------------------


def scan_notes(root: Path, *, limit: int = MAX_NOTES) -> list[Path]:
    """Live MM3 notes in the vault (not archived copies, transcripts or hidden folders)."""
    found: list[Path] = []
    seen = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d for d in dirnames if not d.startswith(".") and d != ARCHIVE_FOLDER.strip("/")
        )
        for name in sorted(filenames):
            if not name.endswith(NOTE_SUFFIX) or name.endswith(TRANSCRIPT_SUFFIX):
                continue
            seen += 1
            if seen > limit:
                return found
            path = Path(dirpath) / name
            if not is_inside(root, path):
                continue
            info = read_identity(path)
            if info is not None and info.is_note:
                found.append(path)
    return found


def _template(library: TemplateLibrary, template_id: str | None) -> Template | None:
    if not template_id:
        return None
    try:
        return library.get(template_id)
    except MM3Error:
        return None


def _missing_sections(parsed: ParsedNote, template: Template | None) -> tuple[str, ...]:
    if template is None:
        return ()
    have = {s.id for s in parsed.note.sections}
    return tuple(
        sid for sid in SUMMARY_IDS if template.section(sid) is not None and sid not in have
    )


def plan_note(
    root: Path, path: Path, library: TemplateLibrary, settings: Settings, text: str | None = None
) -> NotePlan:
    text = read_text(path) if text is None else text
    rel = path.relative_to(root).as_posix()
    info = read_identity(path)
    base: dict[str, Any] = {
        "path": path,
        "rel": rel,
        "mm3_id": info.mm3_id if info else "",
        "title": info.title if info else path.stem,
        "date": info.date if info else None,
        "sha": text_sha(text),
    }
    try:
        parsed = parse_note(text)
    except MM3Error as exc:
        return NotePlan(**base, skip=f"the note cannot be read: {exc.message}")
    if not scan_sections(text).ok:
        return NotePlan(**base, skip="its section markers are damaged (repair them in Review)")
    template = _template(library, parsed.note.meta.template_id)
    add = _missing_sections(parsed, template)
    summary = parsed.note.section("summary")
    rename = (
        summary is not None
        and summary.title == OLD_HEADING
        and template is not None
        and (t := template.section("summary")) is not None
        and t.title == NEW_HEADING
    )
    found = find_companion(path, parsed)
    base["duration"] = found[1].doc.transcript.duration if found is not None else None
    readable = (
        settings.generation.readable_transcript
        and found is not None
        and (find_readable(path, str(parsed.note.meta.id)) is None or not _has_link(text))
    )
    if found is None and add:
        return NotePlan(
            **base,
            rename_heading=rename,
            skip="it has no companion transcript to write the new sections from",
        )
    return NotePlan(**base, add_sections=add, rename_heading=rename, write_readable=readable)


def _has_link(text: str) -> bool:
    return header_transcript_line(text) is not None


def plan_vault(
    root: Path, library: TemplateLibrary, settings: Settings, *, only: Path | None = None
) -> UpgradePlan:
    paths = [only] if only is not None else scan_notes(root)
    return UpgradePlan(tuple(plan_note(root, p, library, settings) for p in paths))


# -- applying ----------------------------------------------------------------------------------


def _neighbours(template: Template | None, section_id: str) -> tuple[list[str], list[str]]:
    """Section ids just before (nearest first) and after ``section_id`` in the template."""
    if template is None:
        return [], []
    ids = [s.id for s in template.sections]
    if section_id not in ids:
        return [], []
    i = ids.index(section_id)
    return list(reversed(ids[:i])), ids[i + 1 :]


async def generate_sections(
    plan: NotePlan,
    text: str,
    *,
    library: TemplateLibrary,
    settings: Settings,
    backend: LLMBackend,
    backend_name: str,
    model: str,
    cloud_consent: bool = False,
    warn: Callable[[str], None] | None = None,
) -> dict[str, Section]:
    """The new sections' content, from the note's companion transcript (the model is called;
    nothing is written)."""
    parsed = parse_note(text)
    found = find_companion(plan.path, parsed)
    if found is None:
        raise MM3Error("E_TRANSCRIPT_MISSING", "The companion transcript is missing.", "")
    transcript = found[1].doc.named()
    template = _template(library, parsed.note.meta.template_id)
    if template is None:
        raise MM3Error("E_TEMPLATE_NOT_FOUND", "The note's template is not available.", "")
    cfg = settings.llm.backends.get(backend_name)
    generator = NoteGenerator(
        backend,
        model,
        template,
        cloud_consent=cloud_consent,
        consent_remembered=bool(cfg and cfg.consent_remembered),
        max_context=settings.generation.max_context,
        think=settings.generation.think,
        warn=warn or (lambda m: None),
    )
    written = await generator.write_sections(parsed.note.meta, transcript, plan.add_sections)
    return {s.id: s for s in written}


def build_upgraded(
    text: str, plan: NotePlan, sections: dict[str, Section], template: Template | None
) -> str:
    """``text`` with the new sections inserted and the heading renamed (pure)."""
    new = text
    for sid in SUMMARY_IDS:  # summary first, so summary-detailed can follow it
        section = sections.get(sid)
        if section is None:
            continue
        after, before = _neighbours(template, sid)
        new, _ = insert_section(new, section, after=after, before=before)
    if plan.rename_heading:
        new = rename_heading(new, "summary", OLD_HEADING, NEW_HEADING)
    return new


async def apply_note(
    root: Path,
    plan: NotePlan,
    *,
    library: TemplateLibrary,
    settings: Settings,
    backend: LLMBackend | None = None,
    backend_name: str = "",
    model: str = "",
    cloud_consent: bool = False,
    when: dt.datetime | None = None,
) -> NoteResult:
    """Upgrade one note. ``backend`` is needed only when sections must be generated."""
    result = NoteResult(plan.rel, "unchanged")
    try:
        text = read_text(plan.path)
    except OSError as exc:
        return NoteResult(plan.rel, "failed", f"The note cannot be read: {exc.strerror}.")
    current = plan_note(root, plan.path, library, settings, text)  # the file may have changed
    if current.skip is not None:
        return NoteResult(plan.rel, "skipped", current.skip)
    if not current.needed:
        return result
    parsed = parse_note(text)
    template = _template(library, parsed.note.meta.template_id)
    sections: dict[str, Section] = {}
    if current.add_sections:
        if backend is None:
            raise MM3Error("E_LLM_CONFIG", "No language model was given for the new sections.", "")
        sections = await generate_sections(
            current,
            text,
            library=library,
            settings=settings,
            backend=backend,
            backend_name=backend_name,
            model=model,
            cloud_consent=cloud_consent,
            warn=result.warnings.append,
        )
        result.added = [s.title for s in sections.values()]
    new_text = build_upgraded(text, current, sections, template)

    readable: Path | None = None
    if current.write_readable:
        found = find_companion(plan.path, parsed)
        if found is not None:
            try:
                readable = write_readable(root, plan.path, found[1].doc, transcript=found[0])
            except MM3Error as exc:
                result.warnings.append(f"The readable transcript was not written: {exc.message}")
    if readable is None:
        readable = find_readable(plan.path, current.mm3_id)
    if readable is not None:
        new_text = with_transcript_link(new_text, readable_link(readable))
        result.readable = readable.relative_to(root).as_posix()

    if new_text != text:
        # Last check before writing: an edit made while the model worked is never overwritten.
        latest = read_text(plan.path)
        info = read_identity(plan.path)
        if text_sha(latest) != current.sha or info is None or info.mm3_id != current.mm3_id:
            return NoteResult(
                plan.rel,
                "skipped",
                "The note changed while it was being updated (edited in Obsidian?). Nothing was "
                "written; run the update again.",
                readable=result.readable,
            )
        archive = archive_note(root, plan.path, when=when)
        result.archive = archive.relative_to(root).as_posix()
        atomic_write_text(plan.path, new_text, overwrite=True, vault_root=root)
    result.status = "updated" if new_text != text or current.write_readable else "unchanged"
    return result


# -- choosing the model ------------------------------------------------------------------------


@dataclass(frozen=True)
class ModelChoice:
    backend_name: str
    model: str
    backend: LLMBackend
    cloud: bool
    """The transcript leaves the machine: the user must agree first (S6)."""


async def choose_model(
    registry: BackendRegistry, settings: Settings, backend: str | None, model: str | None
) -> ModelChoice:
    """The backend and model for the upgrade: the ones asked for, else the default backend's
    default model, else (for a local backend) the suggested installed model. The ADR-0029 check
    refuses models that cannot write notes."""
    name = backend or registry.default_name
    llm = registry.get(name)
    chosen = model or registry.config(name).default_model
    if not chosen and llm.is_local:
        try:
            chosen = suggest(await llm.list_models(), llm, settings.generation.max_context)
        except MM3Error:
            chosen = None
    if not chosen:
        from meetingmaster3.templates.stages import resolve_model

        chosen = resolve_model(settings, name, None)  # raises with a hint
    problem = await model_problem(llm, chosen, settings.generation.max_context)
    if problem is not None:
        raise problem
    cfg = settings.llm.backends.get(name)
    cloud = requires_consent(llm) and not (cfg is not None and cfg.consent_remembered)
    return ModelChoice(name, chosen, llm, cloud)


# -- background run (web) ------------------------------------------------------------------------


@dataclass
class UpgradeRun:
    """One "Update older notes" run, done in the server process, one note at a time."""

    plan: UpgradePlan
    choice: ModelChoice | None
    started: dt.datetime = field(default_factory=dt.datetime.now)
    results: list[NoteResult] = field(default_factory=list)
    current: str = ""
    status: str = "running"
    """``running``, ``done``, ``cancelled`` or ``failed``."""
    error: str = ""
    cancel_requested: bool = False
    task: asyncio.Task[None] | None = field(default=None, repr=False)

    @property
    def total(self) -> int:
        return len(self.plan.todo)

    @property
    def done_count(self) -> int:
        return len(self.results)

    def cancel(self) -> None:
        self.cancel_requested = True

    async def run(
        self,
        root: Path,
        *,
        library: TemplateLibrary,
        settings: Settings,
        cloud_consent: bool = False,
    ) -> None:
        try:
            for plan in self.plan.todo:
                if self.cancel_requested:
                    self.status = "cancelled"
                    return
                self.current = plan.rel
                try:
                    result = await apply_note(
                        root,
                        plan,
                        library=library,
                        settings=settings,
                        backend=self.choice.backend if self.choice else None,
                        backend_name=self.choice.backend_name if self.choice else "",
                        model=self.choice.model if self.choice else "",
                        cloud_consent=cloud_consent,
                    )
                except MM3Error as exc:
                    result = NoteResult(plan.rel, "failed", exc.message)
                    if exc.code in ("E_CONSENT_REQUIRED", "E_LLM_CONNECT", "E_LLM_CONFIG"):
                        self.results.append(result)
                        self.status, self.error = "failed", exc.message
                        return
                self.results.append(result)
            self.status = "cancelled" if self.cancel_requested else "done"
        except Exception as exc:
            log.exception("Note upgrade failed")
            self.status, self.error = "failed", str(exc) or type(exc).__name__
        finally:
            self.current = ""
