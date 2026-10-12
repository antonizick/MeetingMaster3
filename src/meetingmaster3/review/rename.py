"""Rename a meeting's speakers after the note was written (Phase 07 cascade, spec §3).

One new speaker map is applied everywhere a name appears:

* the companion transcript: ``mm3-speakers`` and the visible turn headings
  (``rename_companion_text``; refused with ``transcript_turns_mismatch`` if the user
  restructured the turns);
* the note's frontmatter: ``mm3-speakers`` and ``participants`` (names that came from the old
  map are replaced, people typed in by hand are kept);
* the note's ``Participants`` header line, only if it is still exactly what MM3 wrote;
* names inside MM3 sections (whole-word, case-sensitive). Text outside the markers is never
  rewritten;
* the job folder's speaker map, if the job still exists.

Renaming does not enroll voiceprints: the per-meeting embeddings are deleted when speakers are
first confirmed (Phase 07).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path

from meetingmaster3.domain.meeting import MeetingMeta
from meetingmaster3.domain.transcript import SpeakerMap, clean_name
from meetingmaster3.errors import MM3Error
from meetingmaster3.markdown.diff import DiffRow, side_by_side, unified_diff
from meetingmaster3.markdown.editing import split_document
from meetingmaster3.markdown.note_parser import parse_note
from meetingmaster3.markdown.note_writer import render_header, render_note
from meetingmaster3.markdown.transcript_format import ParsedTranscript
from meetingmaster3.speakers.cascade import apply_speaker_map, rename_companion_text

E_NAME_INVALID = "E_SPEAKER_NAME_INVALID"
MAX_NAME = 80


def replace_names(text: str, replacements: Mapping[str, str]) -> tuple[str, int]:
    """Replace whole-word occurrences of each old name in one pass (so A→B, B→A swaps work).
    Longer names win ("Speaker 10" before "Speaker 1")."""
    olds = sorted((o for o in replacements if o), key=len, reverse=True)
    if not olds:
        return text, 0
    pattern = re.compile(r"(?<![\w])(" + "|".join(re.escape(o) for o in olds) + r")(?![\w])")
    count = 0

    def sub(m: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return replacements[m.group(1)]

    return pattern.sub(sub, text), count


@dataclass(frozen=True)
class SpeakerChange:
    label: str
    old: str
    new: str


@dataclass
class RenamePlan:
    speaker_map: SpeakerMap
    changes: list[SpeakerChange]
    note_text: str
    companion_text: str
    section_hits: dict[str, int] = field(default_factory=dict)
    """Section title → number of names replaced in it."""
    header_updated: bool = False

    def note_diff(self, old: str) -> tuple[str, list[DiffRow]]:
        return unified_diff(old, self.note_text, old_label="note", new_label="renamed"), [
            r for r in side_by_side(old, self.note_text) if r.kind != "equal"
        ]

    def companion_diff(self, old: str) -> list[DiffRow]:
        return [r for r in side_by_side(old, self.companion_text) if r.kind != "equal"]


def validate_names(
    names: Mapping[str, str], labels: list[str], current: Mapping[str, str] | None = None
) -> dict[str, str]:
    """The new ``label → name`` map: ``current`` updated with ``names``. A blank name removes
    the label's name (it goes back to a numbered placeholder); labels not in ``names`` keep
    their current name."""
    out: dict[str, str] = {k: v for k, v in (current or {}).items() if k in labels}
    for label, raw in names.items():
        if label not in labels:
            raise MM3Error(
                E_NAME_INVALID, f"{label!r} is not a speaker in this transcript.", "", 422
            )
        name = clean_name(raw)
        if not name:
            out.pop(label, None)
            continue
        if len(name) > MAX_NAME or any(c in name for c in "[]|#`<>"):
            raise MM3Error(
                E_NAME_INVALID,
                f"The name for {label} is too long or contains [ ] | # ` < or >.",
                "Use a plain name.",
                status_code=422,
            )
        out[label] = name
    return out


def _update_header(text: str, old_meta: MeetingMeta, new_participants: list[str]) -> str:
    """``text`` with its Participants header line updated, if that line is still exactly what
    MM3 wrote for ``old_meta`` (a line the user edited is left alone)."""
    doc = split_document(text)
    preamble = doc.texts[0]
    newline = doc.newline
    old_line = next(
        (
            ln
            for ln in render_header(old_meta, newline).splitlines(keepends=True)
            if ln.startswith("- **Participants:**")
        ),
        "",
    )
    header = parse_note(text).note.header_markdown
    if not old_line or old_line not in header:
        return text
    new_line = f"- **Participants:** {', '.join(new_participants) or 'Not recorded'}{newline}"
    texts = (preamble.replace(old_line, new_line, 1), *doc.texts[1:])
    return replace(doc, texts=texts).join()


def plan_rename(
    note_text: str, companion: ParsedTranscript, companion_text: str, names: Mapping[str, str]
) -> RenamePlan:
    parsed = parse_note(note_text)
    transcript = companion.doc.transcript
    labels = transcript.speaker_labels
    if not labels:
        raise MM3Error(
            "E_NOT_DIARIZED",
            "This meeting's transcript has no separate speakers to rename.",
            "Speakers were not separated when it was processed.",
            status_code=409,
        )
    old_map = companion.doc.speakers
    new_map = SpeakerMap(names=validate_names(names, labels, old_map.names))
    note_old_map = parsed.note.meta.speakers if parsed.note.meta.speakers.names else old_map
    changes = [
        SpeakerChange(
            label, old_map.display_name(label, labels), new_map.display_name(label, labels)
        )
        for label in labels
        if old_map.display_name(label, labels) != new_map.display_name(label, labels)
    ]
    cascade = apply_speaker_map(
        new_map, transcript, meta=parsed.note.meta, companion=companion.doc, old_map=note_old_map
    )
    replacements = {
        note_old_map.display_name(label, labels): new_map.display_name(label, labels)
        for label in labels
        if note_old_map.display_name(label, labels) != new_map.display_name(label, labels)
    }
    note = parsed.note
    hits: dict[str, int] = {}
    for section in parsed.note.sections:
        body, n = replace_names(section.body_markdown, replacements)
        if n:
            hits[section.title or section.id] = n
            note = note.with_section(section.model_copy(update={"body_markdown": body}))
    if cascade.meta is not None:
        note = note.with_meta(cascade.meta)
    rendered = render_note(note, base=parsed)
    header_updated = False
    if cascade.meta is not None and cascade.meta.participants != parsed.note.meta.participants:
        updated = _update_header(rendered, parsed.note.meta, cascade.meta.participants)
        header_updated = updated != rendered
        rendered = updated
    return RenamePlan(
        speaker_map=new_map,
        changes=changes,
        note_text=rendered,
        companion_text=rename_companion_text(companion_text, new_map),
        section_hits=hits,
        header_updated=header_updated,
    )


def companion_rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()
