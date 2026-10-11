"""Regenerate one section of a note in the vault and preview the change (no write).

Used by ``POST /api/notes/regenerate-section`` and by Phase 11's review workspace. The caller
shows the diff and decides whether to apply it (``markdown.sections.replace_section``) and
whether to archive the previous version (``vault.archive.archive_section``).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from meetingmaster3.config.settings import Settings
from meetingmaster3.domain.transcript import Transcript
from meetingmaster3.errors import MM3Error
from meetingmaster3.markdown.diff import diff_stats, side_by_side, unified_diff
from meetingmaster3.markdown.note_parser import ParsedNote, parse_note
from meetingmaster3.markdown.sections import SectionMarkerError, scan_sections
from meetingmaster3.markdown.transcript_format import parse_transcript
from meetingmaster3.templates.generator import regenerate_section
from meetingmaster3.templates.loader import TemplateLibrary
from meetingmaster3.templates.schema import Template, TemplateParams
from meetingmaster3.vault.io import read_text
from meetingmaster3.vault.naming import NOTE_SUFFIX, TRANSCRIPT_SUFFIX
from meetingmaster3.vault.paths import confine, resolve_vault_root

E_NOTE_NOT_FOUND = "E_NOTE_NOT_FOUND"
E_SECTION_NOT_FOUND = "E_SECTION_NOT_FOUND"
E_TRANSCRIPT_MISSING = "E_TRANSCRIPT_MISSING"


@dataclass(frozen=True)
class RegenerationPreview:
    note: str
    """Vault-relative path of the note."""
    section_id: str
    title: str
    old_body: str
    new_body: str
    unified_diff: str
    side_by_side: list[dict[str, Any]]
    stats: dict[str, int]
    template: str
    backend: str
    model: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def note_path(root: Path, relative: str) -> Path:
    path = confine(root, relative)
    if path.suffix != NOTE_SUFFIX or path.name.endswith(TRANSCRIPT_SUFFIX) or not path.is_file():
        raise MM3Error(
            E_NOTE_NOT_FOUND,
            f"There is no note at {relative!r} in the vault.",
            "Give the note's path relative to the vault root, e.g. 'Meetings/2026/2026-10-11 - "
            "Product Sync.md'.",
            status_code=404,
        )
    return path


def load_section(text: str, section_id: str) -> ParsedNote:
    """Parse the note and make sure ``section_id`` is intact (R11)."""
    parsed = parse_note(text)
    scan = scan_sections(text)
    errors = scan.errors_for(section_id)
    if errors:
        raise SectionMarkerError(section_id, errors)
    if parsed.note.section(section_id) is None:
        raise MM3Error(
            E_SECTION_NOT_FOUND,
            f"The note has no section '{section_id}'.",
            f"Sections in this note: {', '.join(s.id for s in parsed.note.sections) or 'none'}.",
            status_code=404,
        )
    return parsed


def companion_transcript(path: Path, parsed: ParsedNote) -> Transcript:
    """The named transcript from the note's companion file (spec §3: graceful degradation)."""
    ref = parsed.note.meta.transcript_ref
    candidates = []
    if ref:
        candidates.append(path.parent / f"{ref}{NOTE_SUFFIX}")
    candidates.append(path.with_name(path.name.removesuffix(NOTE_SUFFIX) + TRANSCRIPT_SUFFIX))
    for candidate in candidates:
        if candidate.is_file() and candidate.resolve().is_relative_to(path.parent.resolve()):
            doc = parse_transcript(read_text(candidate)).doc
            if doc.meeting_id != parsed.note.meta.id:
                continue
            return doc.named()
    raise MM3Error(
        E_TRANSCRIPT_MISSING,
        "This note's companion transcript is missing, so its sections cannot be regenerated.",
        "Put the '.transcript.md' file back next to the note, or process the recording again.",
        status_code=409,
    )


def _template(library: TemplateLibrary, template_id: str | None, default: str) -> Template:
    try:
        return library.get(template_id or default)
    except MM3Error:
        # The note's template was deleted or broken: regenerate with the rules alone.
        return Template(
            id=template_id or "unknown",
            name="Meeting notes",
            sections=(),
            params=TemplateParams(ai_recommendations=False),
            system_prompt="Write clear, well-organised meeting notes.",
            prompts={},
        )


async def preview_regeneration(
    settings: Settings,
    library: TemplateLibrary,
    backend_lookup: Any,
    *,
    note: str,
    section_id: str,
    instructions: str | None = None,
    backend: str | None = None,
    model: str | None = None,
    cloud_consent: bool = False,
) -> RegenerationPreview:
    """Regenerate ``section_id`` of the vault note ``note`` and return the old and new bodies
    with diffs. ``backend_lookup(name)`` returns an LLM backend (the app's registry)."""
    root = resolve_vault_root(settings.vault.path)
    path = note_path(root, note)
    parsed = load_section(read_text(path), section_id)
    meta = parsed.note.meta
    section = parsed.note.section(section_id)
    if section is None:  # pragma: no cover - checked by load_section
        raise MM3Error(E_SECTION_NOT_FOUND, f"The note has no section '{section_id}'.", "")
    transcript = companion_transcript(path, parsed)
    template = _template(library, meta.template_id, settings.generation.default_template)

    name = backend or meta.backend or settings.llm.default_backend
    cfg = settings.llm.backends.get(name)
    chosen = model or (meta.model if name == meta.backend else None) or (cfg and cfg.default_model)
    if not chosen:
        from meetingmaster3.templates.stages import resolve_model

        chosen = resolve_model(settings, name, None)  # raises with a hint
    llm = backend_lookup(name)
    new_body = await regenerate_section(
        parsed.note,
        section_id,
        instructions,
        transcript=transcript,
        template=template,
        backend=llm,
        model=chosen,
        cloud_consent=cloud_consent,
        consent_remembered=bool(cfg and cfg.consent_remembered),
        max_context=settings.generation.max_context,
    )
    rows = side_by_side(section.body_markdown, new_body)
    stats = diff_stats(rows)
    return RegenerationPreview(
        note=path.relative_to(root).as_posix(),
        section_id=section_id,
        title=section.title,
        old_body=section.body_markdown,
        new_body=new_body,
        unified_diff=unified_diff(section.body_markdown, new_body),
        side_by_side=[asdict(r) for r in rows],
        stats={"added": stats.added, "removed": stats.removed, "changed": stats.changed},
        template=template.id,
        backend=name,
        model=chosen,
    )
