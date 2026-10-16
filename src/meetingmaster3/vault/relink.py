"""Re-link Meetings entries whose note moved (a vault folder was renamed or relocated).

The Meetings list stores absolute note paths, so moving a folder or pointing ``vault.path``
somewhere else strands every entry. A note's identity is its ``mm3-id`` frontmatter, which a move
does not change, so an entry is re-linked by finding the live note with the same id inside the
current vault. Nothing is ever written to a note; only the list entry is updated.

An entry is matched only when the answer is clear: exactly one live note carries its id, or
several do and exactly one of them has the old file name. Anything else is reported as ambiguous
and left for the user to choose.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from meetingmaster3.storage.repositories import RecentMeeting, RecentMeetingsRepository
from meetingmaster3.vault.naming import NOTE_SUFFIX, TRANSCRIPT_SUFFIX
from meetingmaster3.vault.paths import is_inside
from meetingmaster3.vault.picker import read_identity

MAX_FILES = 50_000
"""Markdown files examined in one scan; a larger vault is scanned partially (``truncated``)."""


@dataclass
class VaultIndex:
    root: Path
    notes: dict[str, list[Path]] = field(default_factory=dict)
    """Live notes by ``mm3-id``."""
    transcripts: dict[str, list[Path]] = field(default_factory=dict)
    """Companion transcripts (``*.transcript.md``) by ``mm3-id``."""
    by_name: dict[str, list[Path]] = field(default_factory=dict)
    """Every Markdown file by file name, for entries that have no ``mm3-id``."""
    truncated: bool = False


def index_vault(root: Path, *, max_files: int = MAX_FILES) -> VaultIndex:
    """Read the identity of every Markdown file in the vault (hidden folders are skipped)."""
    index = VaultIndex(root)
    seen = 0
    for folder, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for name in sorted(files):
            if not name.endswith(NOTE_SUFFIX) or name.startswith("."):
                continue
            seen += 1
            if seen > max_files:
                index.truncated = True
                return index
            path = Path(folder) / name
            index.by_name.setdefault(name, []).append(path)
            info = read_identity(path)
            if info is None:
                continue
            if info.is_note:
                index.notes.setdefault(info.mm3_id, []).append(path)
            elif info.is_transcript and name.endswith(TRANSCRIPT_SUFFIX):
                index.transcripts.setdefault(info.mm3_id, []).append(path)
    return index


@dataclass(frozen=True)
class Candidate:
    note: Path
    transcript: Path | None

    def rel(self, root: Path) -> str:
        return self.note.relative_to(root).as_posix()


@dataclass(frozen=True)
class Match:
    entry: RecentMeeting
    candidates: tuple[Candidate, ...]
    """What could be linked: one for a clear match, several when ambiguous, none if not found."""

    @property
    def status(self) -> str:
        return {0: "none", 1: "found"}.get(len(self.candidates), "ambiguous")


def is_orphan(entry: RecentMeeting, root: Path) -> bool:
    """The entry's note is gone or lies outside the vault."""
    path = Path(entry.note_path)
    return not path.is_file() or not is_inside(root, path)


def _pick_transcript(
    index: VaultIndex, mm3_id: str | None, note: Path, old: RecentMeeting
) -> Path | None:
    options = index.transcripts.get(mm3_id, []) if mm3_id else []
    if not options:
        return None
    wanted = (
        note.with_name(note.name.removesuffix(NOTE_SUFFIX) + TRANSCRIPT_SUFFIX),
        note.parent / Path(old.transcript_path).name if old.transcript_path else None,
    )
    for want in wanted:
        if want is not None and want in options:
            return want
    return options[0] if len(options) == 1 else None


def find_match(index: VaultIndex, entry: RecentMeeting) -> Match:
    if entry.mm3_id:
        found = list(index.notes.get(entry.mm3_id, []))
    else:  # a note without an MM3 identity: the same file name, if it is unambiguous
        found = list(index.by_name.get(Path(entry.note_path).name, []))
    if len(found) > 1:  # several live copies: the one that kept its file name wins, if only one
        same_name = [p for p in found if p.name == Path(entry.note_path).name]
        if len(same_name) == 1:
            found = same_name
    return Match(
        entry,
        tuple(Candidate(p, _pick_transcript(index, entry.mm3_id, p, entry)) for p in found),
    )


def plan_relink(root: Path, entries: Iterable[RecentMeeting]) -> list[Match]:
    """A match for every orphaned entry (indexes the vault only if there is one)."""
    orphans = [e for e in entries if is_orphan(e, root)]
    if not orphans:
        return []
    index = index_vault(root)
    return [find_match(index, e) for e in orphans]


def apply_relink(
    repo: RecentMeetingsRepository, entry: RecentMeeting, candidate: Candidate
) -> None:
    repo.relink(
        entry.note_path,
        str(candidate.note),
        str(candidate.transcript) if candidate.transcript else None,
    )


def apply_clear_matches(repo: RecentMeetingsRepository, matches: Iterable[Match]) -> int:
    """Re-link every entry that has exactly one candidate; returns how many were linked."""
    done = 0
    for match in matches:
        if match.status == "found":
            apply_relink(repo, match.entry, match.candidates[0])
            done += 1
    return done
