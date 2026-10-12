"""Save the workspace's edits to the vault, detecting edits made elsewhere (spec §3).

The editor's parts are joined against the *base* text the workspace was opened from. Before the
atomic write, the file on disk is compared with that base; if it changed (Obsidian, sync, another
tab), nothing is written and the caller gets a :class:`SaveConflict` with both versions, so the
user can keep theirs, take the file's, or compare both.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from meetingmaster3.errors import MM3Error
from meetingmaster3.markdown.editing import Edits, apply_edits, split_document
from meetingmaster3.markdown.note_parser import parse_note
from meetingmaster3.review.store import ReviewStore, text_sha
from meetingmaster3.vault.io import atomic_write_text, read_text

E_BASE_GONE = "E_BASE_GONE"
E_NOTE_CHANGED = "E_NOTE_CHANGED"
E_NOTE_ID_CHANGED = "E_NOTE_ID_CHANGED"


class SaveConflict(MM3Error):
    """The file changed on disk since the workspace loaded it."""

    def __init__(self, theirs: str, mine: str, theirs_sha: str) -> None:
        super().__init__(
            E_NOTE_CHANGED,
            "The note was changed outside MeetingMaster3 since you opened it.",
            "Compare the two versions, then keep yours, take the file's, or merge by hand.",
            status_code=409,
        )
        self.theirs = theirs
        self.mine = mine
        self.theirs_sha = theirs_sha


@dataclass(frozen=True)
class SaveResult:
    sha: str
    written: bool


def base_text(store: ReviewStore, base_sha: str) -> str:
    text = store.base(base_sha)
    if text is None:
        raise MM3Error(
            E_BASE_GONE,
            "The version of the note this editor was opened from is no longer available.",
            "Reload the page. Your autosaved draft can be restored if the note's sections are "
            "unchanged.",
            status_code=409,
        )
    return text


def check_note(text: str, mm3_id: str) -> None:
    """Refuse a result that is no longer an MM3 note of the same meeting."""
    parsed = parse_note(text)  # raises not_an_mm3_note / invalid_mm3_id
    if str(parsed.note.meta.id) != mm3_id:
        raise MM3Error(
            E_NOTE_ID_CHANGED,
            "The edit changes the note's 'mm3-id' property.",
            "Put the original mm3-id back: it links the note to its transcript and recording.",
            status_code=422,
        )


def build_text(
    store: ReviewStore, base_sha: str, edits: Edits, *, allow_marker_changes: bool = False
) -> str:
    """The note text the editor's parts describe."""
    return apply_edits(
        split_document(base_text(store, base_sha)),
        edits,
        allow_marker_changes=allow_marker_changes,
    )


def write_checked(
    root: Path, path: Path, text: str, *, expected_sha: str, mine: str | None = None
) -> str:
    """Atomically replace the vault file with ``text`` if it still has ``expected_sha``;
    otherwise raise :class:`SaveConflict`. Returns the new SHA."""
    current = read_text(path)
    current_sha = text_sha(current)
    if current_sha != expected_sha:
        raise SaveConflict(current, mine if mine is not None else text, current_sha)
    if current != text:
        atomic_write_text(path, text, overwrite=True, vault_root=root)
    return text_sha(text)


def save_note(
    root: Path,
    path: Path,
    mm3_id: str,
    store: ReviewStore,
    *,
    base_sha: str,
    edits: Edits,
    force_sha: str | None = None,
    allow_marker_changes: bool = False,
) -> SaveResult:
    """Save ``edits``. ``force_sha`` is the SHA of the disk version the user chose to overwrite
    ("keep mine"); it must still be the version on disk."""
    text = build_text(store, base_sha, edits, allow_marker_changes=allow_marker_changes)
    check_note(text, mm3_id)
    before = read_text(path)
    sha = write_checked(root, path, text, expected_sha=force_sha or base_sha)
    store.put_base(text)
    store.clear_draft()
    return SaveResult(sha, written=before != text)
