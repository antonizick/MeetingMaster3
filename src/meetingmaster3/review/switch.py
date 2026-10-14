"""Switch a note to another template: regenerate the whole note (R12, spec §3).

The new note keeps the meeting's metadata, the companion link and every property the user
added. Text the user wrote outside the MM3 sections (including any damaged sections, which are
plain text to the parser) is appended under a "Preserved notes" heading, so nothing is lost; the
previous note is also archived whole (``vault.archive.archive_note``) when the switch is applied.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from meetingmaster3.config.settings import Settings
from meetingmaster3.domain.note import HEADER_LINE_RE, Note, split_lines
from meetingmaster3.markdown.note_parser import ParsedNote, parse_note
from meetingmaster3.markdown.note_writer import (
    TRANSCRIPT_LINE_PREFIX,
    build_note,
    render_note,
    with_transcript_link,
)
from meetingmaster3.templates.generator import ContextFn, NoteGenerator, ProgressFn, StepFn
from meetingmaster3.templates.loader import TemplateLibrary
from meetingmaster3.templates.regenerate import choose_model, companion_transcript

PRESERVED_HEADING = "## Preserved notes"
_H1 = re.compile(r"^# \S")


def preserved_text(note: Note) -> str:
    """The user's own text outside the sections: the preamble without the H1 and MM3's header
    lines, the text between sections and after the last one. Blank-only parts are dropped."""
    lines = split_lines(note.preamble)
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i < len(lines) and _H1.match(lines[i]):
        i += 1
        while i < len(lines) and HEADER_LINE_RE.match(lines[i].rstrip("\r\n")):
            i += 1
    parts = ["".join(lines[i:]), *note.interstitial_text, note.trailing_text]
    kept = []
    for part in parts:
        # A "Preserved notes" heading from an earlier switch is dropped, so it never nests.
        lines = [ln for ln in part.replace("\r\n", "\n").split("\n") if ln != PRESERVED_HEADING]
        text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip("\n")
        if text.strip():
            kept.append(text)
    return "\n\n".join(kept)


@dataclass(frozen=True)
class SwitchResult:
    text: str
    template: str
    backend: str
    model: str
    preserved: bool
    warnings: tuple[str, ...]

    def info(self) -> dict[str, Any]:
        return {"template": self.template, "backend": self.backend, "model": self.model}


def with_preserved(text: str, preserved: str, newline: str) -> str:
    if not preserved:
        return text
    body = preserved.replace("\n", newline)
    sep = "" if text.endswith(newline) else newline
    return f"{text}{sep}{newline}{PRESERVED_HEADING}{newline}{newline}{body}{newline}"


async def switch_template(
    settings: Settings,
    library: TemplateLibrary,
    backend_lookup: Any,
    *,
    path: Path,
    text: str,
    template_id: str,
    backend: str | None = None,
    model: str | None = None,
    cloud_consent: bool = False,
    now: dt.datetime | None = None,
    progress: ProgressFn | None = None,
    step: StepFn | None = None,
    on_context: ContextFn | None = None,
) -> SwitchResult:
    """Generate the note again with ``template_id`` and return the new text (nothing is
    written). Needs the companion transcript (``E_TRANSCRIPT_MISSING`` otherwise)."""
    parsed: ParsedNote = parse_note(text)
    transcript = companion_transcript(path, parsed)
    template = library.get(template_id)
    meta = parsed.note.meta
    name, chosen = choose_model(settings, meta.backend, meta.model, backend, model)
    cfg = settings.llm.backends.get(name)
    generator = NoteGenerator(
        backend_lookup(name),
        chosen,
        template,
        cloud_consent=cloud_consent,
        consent_remembered=bool(cfg and cfg.consent_remembered),
        max_context=settings.generation.max_context,
        think=settings.generation.think,
    )
    if progress is not None:
        generator.progress = progress
    if step is not None:
        generator.step = step
    if on_context is not None:
        on_context(transcript.duration, bool(generator.backend.is_local))
    result = await generator.generate(meta, transcript)
    new_meta = meta.model_copy(
        update={
            "template_id": template.id,
            "backend": name,
            "model": chosen,
            "generated_at": (now or dt.datetime.now()).replace(microsecond=0),
        }
    )
    newline = parsed.note.newline
    note = build_note(
        new_meta,
        result.sections,
        extra_properties=parsed.note.extra_properties,
        newline=newline,
    )
    preserved = preserved_text(parsed.note)
    new_text = render_note(note)
    old_link = next(
        (
            ln
            for ln in parsed.note.preamble.splitlines(keepends=True)
            if ln.startswith(TRANSCRIPT_LINE_PREFIX)
        ),
        None,
    )
    if old_link is not None:  # keep the link to the readable transcript (R25)
        new_text = with_transcript_link(new_text, line=old_link)
    new_text = with_preserved(new_text, preserved, newline)
    if parsed.bom:
        new_text = "﻿" + new_text
    return SwitchResult(
        new_text, template.id, name, chosen, bool(preserved), tuple(result.warnings)
    )
