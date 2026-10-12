"""Write a note's readable transcript into the vault (R25, ADR-0031).

The file sits next to the note as ``<note stem> (Transcript).md``. It is rewritten every time the
companion transcript is written. A file of that name that is not this meeting's readable
transcript (no matching ``mm3-id`` and ``mm3-kind``) is never replaced: the next free name,
``<note stem> (Transcript 2).md`` and so on, is used instead.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from meetingmaster3.domain.transcript import CompanionTranscript
from meetingmaster3.errors import MM3Error
from meetingmaster3.markdown.readable_transcript import render_readable
from meetingmaster3.markdown.transcript_format import parse_transcript
from meetingmaster3.vault.io import atomic_write_text, read_text
from meetingmaster3.vault.naming import NOTE_SUFFIX, readable_names
from meetingmaster3.vault.picker import read_identity

log = logging.getLogger(__name__)


def find_readable(note: Path, mm3_id: str) -> Path | None:
    """This meeting's existing readable transcript next to ``note``, if there is one."""
    for name in readable_names(note.name.removesuffix(NOTE_SUFFIX)):
        path = note.with_name(name)
        if not os.path.lexists(path):
            continue
        info = read_identity(path)
        if info is not None and info.is_readable and info.mm3_id == mm3_id:
            return path
    return None


def readable_target(note: Path, mm3_id: str) -> tuple[Path, bool]:
    """``(path, ours)``: this meeting's existing readable file, or the first free name."""
    existing = find_readable(note, mm3_id)
    if existing is not None:
        return existing, True
    for name in readable_names(note.name.removesuffix(NOTE_SUFFIX)):
        path = note.with_name(name)
        if not os.path.lexists(path):
            return path, False
    raise MM3Error(
        "E_READABLE_NAME_TAKEN",
        f"Every name for the readable transcript of {note.name!r} is taken by other files.",
        "Rename or move the files called '... (Transcript).md' next to the note.",
        status_code=409,
    )


def write_readable(
    root: Path, note: Path, doc: CompanionTranscript, *, transcript: Path | None = None
) -> Path:
    """Write (or refresh) the readable transcript of ``doc`` next to ``note``; returns its path.

    ``transcript`` is the companion file, for the link in the properties. The write is atomic and
    confined to the vault; an unchanged file is not touched.
    """
    path, ours = readable_target(note, str(doc.meeting_id))
    text = render_readable(
        doc,
        note_link=note.name.removesuffix(NOTE_SUFFIX),
        transcript_link=transcript.name.removesuffix(NOTE_SUFFIX) if transcript else None,
    )
    if ours:
        try:
            if read_text(path) == text:
                return path
        except OSError:
            pass
    atomic_write_text(path, text, overwrite=ours, vault_root=root)
    return path


def readable_link(path: Path) -> str:
    """Wikilink target (without brackets) of a readable transcript file."""
    return path.name.removesuffix(NOTE_SUFFIX)


def refresh_readable(root: Path, note: Path, companion: Path, *, enabled: bool) -> Path | None:
    """Rewrite the readable transcript from the companion file on disk, after the companion
    changed (speaker rename, link-transcript). When the feature is off, an existing readable
    file is still refreshed so it never goes stale; none is created. Problems are logged and
    give ``None``: the readable copy must never block the change that triggered it."""
    try:
        doc = parse_transcript(read_text(companion)).doc
        if not enabled and find_readable(note, str(doc.meeting_id)) is None:
            return None
        return write_readable(root, note, doc, transcript=companion)
    except (MM3Error, OSError) as exc:
        log.warning("readable transcript not refreshed: %s", getattr(exc, "code", exc))
        return None
