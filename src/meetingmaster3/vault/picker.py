"""Browse the vault for MM3 notes to re-open (spec §9), confined to the vault root (S4).

Only folders and ``.md`` files whose frontmatter has an ``mm3-id`` are listed. Companion
transcripts, archived copies (``mm3-archived``) and hidden folders (``.obsidian``, ``.trash``)
are skipped. Only the start of each file is read.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from meetingmaster3.errors import MM3Error
from meetingmaster3.markdown.frontmatter import FrontmatterError, split_frontmatter
from meetingmaster3.markdown.note_parser import BOM, text_value
from meetingmaster3.vault.naming import NOTE_SUFFIX, TRANSCRIPT_SUFFIX
from meetingmaster3.vault.paths import confine, is_inside

HEAD_BYTES = 64 * 1024
MAX_FILES = 2000
"""Files examined per folder listing; a larger folder is listed partially (``truncated``)."""


@dataclass(frozen=True)
class NoteInfo:
    mm3_id: str
    title: str
    date: str | None
    archived: bool = False
    is_transcript: bool = False


def read_identity(path: Path) -> NoteInfo | None:
    """The MM3 identity of a vault file from its frontmatter, or ``None`` if it has none."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(HEAD_BYTES)
    except OSError:
        return None
    text = head.decode("utf-8", errors="replace").removeprefix(BOM)
    try:
        fm, _ = split_frontmatter(text)
    except FrontmatterError:
        return None
    if fm is None or not isinstance(fm.data, dict) or fm.data.get("mm3-id") is None:
        return None
    date = fm.data.get("date")
    return NoteInfo(
        mm3_id=str(fm.data["mm3-id"]),
        title=text_value(fm.data.get("title")) or path.stem,
        date=(text_value(date) or "")[:10] or None,
        archived="mm3-archived" in fm.data,
        is_transcript="mm3-note" in fm.data or path.name.endswith(TRANSCRIPT_SUFFIX),
    )


@dataclass(frozen=True)
class Entry:
    name: str
    path: str
    """Relative to the vault root, with ``/`` separators."""
    kind: str
    """``dir`` or ``note``."""
    title: str = ""
    date: str | None = None
    mm3_id: str | None = None


@dataclass
class Listing:
    folder: str
    """Relative to the vault root ('' for the root)."""
    parent: str | None
    entries: list[Entry] = field(default_factory=list)
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "entries": [asdict(e) for e in self.entries]}


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def browse(root: Path, folder: str = "") -> Listing:
    """List the sub-folders and MM3 notes of ``folder`` (relative to the vault ``root``)."""
    target = confine(root, folder) if folder.strip("/ ") else root
    if not target.is_dir():
        raise MM3Error(
            "E_FOLDER_NOT_FOUND",
            "That folder is not in the vault.",
            "Go back to the vault root and browse from there.",
            status_code=404,
        )
    rel = "" if target == root else _relative(root, target)
    parent = None if not rel else (rel.rsplit("/", 1)[0] if "/" in rel else "")
    listing = Listing(folder=rel, parent=parent)
    dirs: list[Entry] = []
    notes: list[Entry] = []
    examined = 0
    try:
        children = sorted(os.scandir(target), key=lambda d: d.name.casefold())
    except OSError as exc:
        raise MM3Error(
            "E_FOLDER_UNREADABLE", f"The folder cannot be read: {exc.strerror}.", ""
        ) from exc
    for child in children:
        if child.name.startswith("."):
            continue
        path = Path(child.path)
        if not is_inside(root, path):  # a symlink pointing out of the vault
            continue
        if child.is_dir():
            dirs.append(Entry(child.name, _relative(root, path), "dir"))
            continue
        if (
            not child.is_file()
            or not child.name.endswith(NOTE_SUFFIX)
            or child.name.endswith(TRANSCRIPT_SUFFIX)
        ):
            continue
        examined += 1
        if examined > MAX_FILES:
            listing.truncated = True
            break
        info = read_identity(path)
        if info is None or info.archived or info.is_transcript:
            continue
        notes.append(
            Entry(
                child.name,
                _relative(root, path),
                "note",
                title=info.title,
                date=info.date,
                mm3_id=info.mm3_id,
            )
        )
    listing.entries = dirs + notes
    return listing


def find_companions(root: Path, mm3_id: str, *, limit: int = 20000) -> list[Path]:
    """Companion transcripts anywhere in the vault whose ``mm3-id`` is ``mm3_id`` (used to
    locate a moved transcript). At most ``limit`` Markdown files are examined."""
    found: list[Path] = []
    seen = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if not name.endswith(NOTE_SUFFIX):
                continue
            seen += 1
            if seen > limit:
                return found
            path = Path(dirpath) / name
            if not is_inside(root, path):
                continue
            info = read_identity(path)
            if info and info.is_transcript and info.mm3_id == mm3_id and not info.archived:
                found.append(path)
    return found
