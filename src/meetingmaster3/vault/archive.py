"""Archives of replaced drafts (R12).

* Section: ``<output folder>/Archive/YYYY-MM-DD - Title.<section-id>.YYYYMMDD-HHMM.md``
* Whole note (template switch): ``<output folder>/Archive/YYYY-MM-DD - Title.YYYYMMDD-HHMM.md``

Archives carry an ``mm3-archived`` property so re-open pickers can skip them.
"""

from __future__ import annotations

import datetime as dt
import os
import uuid
from pathlib import Path

from meetingmaster3.domain.note import Section
from meetingmaster3.markdown.frontmatter import render_frontmatter, split_frontmatter, wikilink
from meetingmaster3.markdown.sections import detect_newline, render_inner
from meetingmaster3.vault.io import atomic_write_text, read_text
from meetingmaster3.vault.naming import NOTE_SUFFIX
from meetingmaster3.vault.paths import ensure_folder

ARCHIVE_FOLDER = "Archive"


def archive_stamp(when: dt.datetime) -> str:
    return f"{when:%Y%m%d-%H%M}"


def _now() -> dt.datetime:
    return dt.datetime.now().replace(microsecond=0)


def _free(path_without_suffix: str) -> Path:
    n = 1
    while True:
        name = path_without_suffix + ("" if n == 1 else f" ({n})") + NOTE_SUFFIX
        if not os.path.lexists(name):
            return Path(name)
        n += 1


def section_archive_path(folder: Path, stem: str, section_id: str, when: dt.datetime) -> Path:
    """A free archive path for one section (``folder`` is the note's output folder)."""
    return _free(str(folder / ARCHIVE_FOLDER / f"{stem}.{section_id}.{archive_stamp(when)}"))


def note_archive_path(folder: Path, stem: str, when: dt.datetime) -> Path:
    return _free(str(folder / ARCHIVE_FOLDER / f"{stem}.{archive_stamp(when)}"))


def _stem(note_path: Path) -> str:
    return note_path.name.removesuffix(NOTE_SUFFIX)


def archive_section(
    vault_root: Path,
    note_path: Path,
    section: Section,
    *,
    meeting_id: uuid.UUID,
    when: dt.datetime | None = None,
    newline: str = "\n",
) -> Path:
    """Save the previous version of ``section`` before it is replaced. Returns the new path."""
    when = when or _now()
    folder = ensure_folder(vault_root, note_path.parent.relative_to(vault_root) / ARCHIVE_FOLDER)
    target = section_archive_path(folder.parent, _stem(note_path), section.id, when)
    fm = render_frontmatter(
        {
            "mm3-archived": when,
            "mm3-archived-from": wikilink(_stem(note_path)),
            "mm3-archived-section": section.id,
            "mm3-archived-id": str(meeting_id),
        },
        newline=newline,
    )
    body = render_inner(section.title, section.body_markdown, newline)
    return atomic_write_text(target, fm + body, vault_root=vault_root)


def archive_note(vault_root: Path, note_path: Path, *, when: dt.datetime | None = None) -> Path:
    """Copy the whole note into the archive before a template switch. The copy is the original
    text with ``mm3-archived`` and ``mm3-archived-from`` added to its frontmatter (every other
    byte unchanged)."""
    when = when or _now()
    text = read_text(note_path)
    folder = ensure_folder(vault_root, note_path.parent.relative_to(vault_root) / ARCHIVE_FOLDER)
    target = note_archive_path(folder.parent, _stem(note_path), when)
    bom = "﻿" if text.startswith("﻿") else ""
    fm, body = split_frontmatter(text.removeprefix(bom))
    added = {"mm3-archived": when, "mm3-archived-from": wikilink(_stem(note_path))}
    newline = detect_newline(text)
    if fm is None:
        archived = render_frontmatter(added, newline=newline) + body
    else:
        archived = render_frontmatter({**fm.data, **added}, newline=newline, base=fm) + body
    return atomic_write_text(target, bom + archived, vault_root=vault_root)
