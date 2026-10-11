"""Parse an MM3 note (frontmatter + H1 + header + marked sections) into a :class:`Note`.

Parsing is lenient about user-edited properties (a string where a list was expected, a date
without a time) and strict about section markers (R11): damaged sections are left in the
surrounding text, reported in :attr:`ParsedNote.marker_errors`, and never guessed at.
"""

from __future__ import annotations

import datetime as dt
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from meetingmaster3.domain.meeting import MeetingMeta
from meetingmaster3.domain.note import FORMAT_VERSION, NOTE_KEYS, Block, Note, Section, TextBlock
from meetingmaster3.domain.transcript import SPEAKER_LABEL_RE, SpeakerMap, clean_name
from meetingmaster3.errors import MM3Error
from meetingmaster3.markdown.frontmatter import ParsedFrontmatter, parse_wikilink, split_frontmatter
from meetingmaster3.markdown.sections import MarkerError, detect_newline, parse_inner, scan_sections

BOM = "\ufeff"


class NoteParseError(MM3Error):
    pass


@dataclass(frozen=True)
class ParsedNote:
    """A parsed note plus what is needed to re-render it without disturbing the file."""

    note: Note
    frontmatter: ParsedFrontmatter
    marker_errors: tuple[MarkerError, ...] = ()
    warnings: tuple[str, ...] = ()
    bom: bool = False
    raw_sections: dict[str, tuple[Section, str]] = field(default_factory=dict, repr=False)
    """Section id → (section as parsed, its exact text from open marker to close marker)."""

    @property
    def ok(self) -> bool:
        return not self.marker_errors


def text_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        return ", ".join(str(v) for v in value if v is not None)
    if isinstance(value, dt.date):
        return value.isoformat()
    return str(value)


def list_value(value: Any, *, split: str = r",") -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [s for v in value if v is not None and (s := text_value(v))]
    if isinstance(value, str):
        return [p for p in re.split(split, value) if p.strip()]
    return [text_value(value) or ""]


def datetime_value(value: Any, key: str, warnings: list[str]) -> dt.datetime | None:
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value
    if isinstance(value, dt.date):
        return dt.datetime.combine(value, dt.time())
    if isinstance(value, str) and value.strip():
        try:
            return dt.datetime.fromisoformat(value.strip())
        except ValueError:
            pass
    warnings.append(f"'{key}' is not a date ({value!r}); ignored")
    return None


def speakers_value(value: Any, warnings: list[str]) -> SpeakerMap:
    if value is None:
        return SpeakerMap()
    if not isinstance(value, dict):
        warnings.append("'mm3-speakers' is not a label: name mapping; ignored")
        return SpeakerMap()
    names: dict[str, str] = {}
    for label, name in value.items():
        label_s, name_s = str(label), clean_name(text_value(name) or "")
        if SPEAKER_LABEL_RE.match(label_s) and name_s:
            names[label_s] = name_s
        else:
            warnings.append(f"'mm3-speakers' entry {label!r} ignored")
    return SpeakerMap(names=names)


def meeting_id(data: dict[str, Any]) -> uuid.UUID:
    raw = data.get("mm3-id")
    if raw is None:
        raise NoteParseError(
            "not_an_mm3_note",
            "This note has no 'mm3-id' property, so it was not written by MeetingMaster3.",
            "Open a note that MeetingMaster3 wrote, or process the meeting audio again.",
        )
    try:
        return uuid.UUID(str(raw))
    except ValueError as exc:
        raise NoteParseError(
            "invalid_mm3_id",
            f"The note's 'mm3-id' ({raw!r}) is not a valid id.",
            "Restore the original 'mm3-id' value (see the companion transcript's frontmatter).",
        ) from exc


def meta_from_frontmatter(
    data: dict[str, Any], warnings: list[str]
) -> tuple[MeetingMeta, int, dict[str, Any]]:
    """``(meta, format_version, extra_properties)`` from parsed frontmatter."""
    version = data.get("mm3-version", FORMAT_VERSION)
    if not isinstance(version, int) or isinstance(version, bool):
        warnings.append(f"'mm3-version' is not a number ({version!r}); assuming {FORMAT_VERSION}")
        version = FORMAT_VERSION
    elif version > FORMAT_VERSION:
        warnings.append(f"written by a newer MeetingMaster3 (format {version})")
    meta = MeetingMeta(
        id=meeting_id(data),
        title=text_value(data.get("title")) or "",
        date=datetime_value(data.get("date"), "date", warnings),
        participants=list_value(data.get("participants")),
        tags=list_value(data.get("tags"), split=r"[,\s]+"),
        location=text_value(data.get("location")),
        template_id=text_value(data.get("mm3-template")),
        backend=text_value(data.get("mm3-backend")),
        model=text_value(data.get("mm3-model")),
        generated_at=datetime_value(data.get("mm3-generated"), "mm3-generated", warnings),
        audio_ref=parse_wikilink(data.get("mm3-audio")),
        transcript_ref=parse_wikilink(data.get("mm3-transcript")),
        speakers=speakers_value(data.get("mm3-speakers"), warnings),
    )
    extras = {k: v for k, v in data.items() if k not in NOTE_KEYS}
    return meta, version, extras


def parse_note(text: str) -> ParsedNote:
    """Parse a note. Raises :class:`NoteParseError` if it is not an MM3 note."""
    bom = text.startswith(BOM)
    if bom:
        text = text[1:]
    fm, body = split_frontmatter(text)
    if fm is None:
        raise NoteParseError(
            "not_an_mm3_note",
            "This file has no frontmatter, so it was not written by MeetingMaster3.",
            "Open a note that MeetingMaster3 wrote.",
        )
    warnings: list[str] = []
    meta, version, extras = meta_from_frontmatter(fm.data, warnings)

    scan = scan_sections(body)
    errors = list(scan.errors)
    blocks: list[Block] = []
    raw_sections: dict[str, tuple[Section, str]] = {}
    pos = 0
    for span in scan.sections:
        title, body_md = parse_inner(body[span.inner_start : span.inner_end])
        try:
            section = Section(id=span.id, title=title, body_markdown=body_md)
        except ValidationError as exc:
            msg = exc.errors()[0]["msg"]
            errors.append(MarkerError("invalid_content", span.open.line, msg, (span.id,)))
            continue
        blocks.append(TextBlock(text=body[pos : span.open.start]))
        blocks.append(section)
        raw_sections[span.id] = (section, body[span.open.start : span.close.end])
        pos = span.close.end
    blocks.append(TextBlock(text=body[pos:]))

    note = Note(
        meta=meta,
        extra_properties=extras,
        format_version=version,
        blocks=blocks,
        newline=detect_newline(text),
    )
    errors.sort(key=lambda e: e.line)
    return ParsedNote(
        note=note,
        frontmatter=fm,
        marker_errors=tuple(errors),
        warnings=tuple(warnings),
        bom=bom,
        raw_sections=raw_sections,
    )
