"""Note file names: ``YYYY-MM-DD - Title.md`` and ``YYYY-MM-DD - Title.transcript.md`` (spec §5).

Titles are sanitised per R13 and collisions get `` (2)``, `` (3)``, ... so nothing is ever
overwritten silently. A note and its companion always share one stem.
"""

from __future__ import annotations

import datetime as dt
import os
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from meetingmaster3.domain.meeting import UNTITLED
from meetingmaster3.errors import MM3Error

FORBIDDEN_CHARS = frozenset('*"\\/<>:|?#^[]')
"""Characters Obsidian or common filesystems reject in file names (R13)."""
MAX_TITLE_BYTES = 150
"""UTF-8 bytes. Leaves room for the date, the collision and archive suffixes and ``.md``
within the usual 255-byte file-name limit."""
NOTE_SUFFIX = ".md"
TRANSCRIPT_SUFFIX = ".transcript.md"


def sanitize_title(title: str, *, max_bytes: int = MAX_TITLE_BYTES) -> str:
    """A title that is safe as part of a file name and as an Obsidian wikilink target."""
    text = unicodedata.normalize("NFC", title)
    chars = []
    for c in text:
        category = unicodedata.category(c)
        if category == "Cf":  # zero-width and bidi-override characters: drop
            continue
        chars.append(" " if c in FORBIDDEN_CHARS or category in ("Cc", "Zl", "Zp") else c)
    text = " ".join("".join(chars).split()).strip(" .")
    encoded = text.encode("utf-8")
    if len(encoded) > max_bytes:
        text = encoded[:max_bytes].decode("utf-8", errors="ignore").strip(" .")
    return text or UNTITLED


def note_stem(date: dt.date, title: str) -> str:
    return f"{date:%Y-%m-%d} - {sanitize_title(title)}"


def with_counter(stem: str, n: int) -> str:
    return stem if n <= 1 else f"{stem} ({n})"


@dataclass(frozen=True)
class NotePaths:
    folder: Path
    stem: str

    @property
    def note(self) -> Path:
        return self.folder / (self.stem + NOTE_SUFFIX)

    @property
    def transcript(self) -> Path:
        return self.folder / (self.stem + TRANSCRIPT_SUFFIX)

    @property
    def note_link(self) -> str:
        """Wikilink target of the note (``[[...]]`` without brackets)."""
        return self.stem

    @property
    def transcript_link(self) -> str:
        return self.stem + TRANSCRIPT_SUFFIX.removesuffix(NOTE_SUFFIX)


def allocate_note_paths(folder: Path, date: dt.date, title: str, *, limit: int = 1000) -> NotePaths:
    """The first free stem for this meeting: neither the note nor its companion exists."""
    base = note_stem(date, title)
    for n in range(1, limit + 1):
        paths = NotePaths(folder, with_counter(base, n))
        if not os.path.lexists(paths.note) and not os.path.lexists(paths.transcript):
            return paths
    raise MM3Error(
        "vault_name_exhausted",
        f"More than {limit} notes are already named '{base}'.",
        "Give the meeting a more specific title.",
    )
