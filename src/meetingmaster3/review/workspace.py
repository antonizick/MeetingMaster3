"""Load a note into the review workspace: find it, its companion transcript and its audio.

Degradation (spec §3, §9): without a companion transcript the note opens in note-only mode
(regeneration and renaming disabled); a note without any MM3 section markers, or one that cannot
be parsed, opens read-only. Missing audio (retention) only hides the player.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from meetingmaster3.domain.transcript import CompanionTranscript, natural_key
from meetingmaster3.errors import MM3Error
from meetingmaster3.jobs.files import job_dir
from meetingmaster3.jobs.retention import RetentionStatus
from meetingmaster3.markdown.editing import EditableDocument, split_document
from meetingmaster3.markdown.note_parser import NoteParseError, ParsedNote, parse_note
from meetingmaster3.markdown.transcript_format import ParsedTranscript
from meetingmaster3.review.store import ReviewStore, text_sha
from meetingmaster3.storage.repositories import RecentMeeting, RecentMeetingsRepository
from meetingmaster3.templates.regenerate import find_companion
from meetingmaster3.vault.io import read_text
from meetingmaster3.vault.naming import NOTE_SUFFIX, TRANSCRIPT_SUFFIX
from meetingmaster3.vault.paths import confine, is_inside
from meetingmaster3.vault.picker import read_identity

if TYPE_CHECKING:
    from meetingmaster3.jobs.runner import JobRunner

E_NOTE_NOT_FOUND = "E_NOTE_NOT_FOUND"
SPEAKER_COLOURS = 8
WRITTEN_FILE = "written.json"

AudioState = Literal["ok", "expired", "missing", "none"]


def not_found(detail: str = "") -> MM3Error:
    return MM3Error(
        E_NOTE_NOT_FOUND,
        "This meeting's note was not found in the vault" + (f" ({detail})." if detail else "."),
        "It may have been moved or renamed. Use 'Open a note' to pick it from the vault.",
        status_code=404,
    )


def check_mm3_id(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError as exc:
        raise not_found("not a meeting id") from exc


def _matches(root: Path, path: Path, mm3_id: str) -> bool:
    if not path.is_file() or not is_inside(root, path) or path.suffix != NOTE_SUFFIX:
        return False
    if path.name.endswith(TRANSCRIPT_SUFFIX):
        return False
    info = read_identity(path)
    return info is not None and info.is_note and info.mm3_id == mm3_id


def locate_note(
    root: Path, recents: RecentMeetingsRepository, mm3_id: str, hint: str | None = None
) -> tuple[Path, RecentMeeting | None]:
    """The vault file of meeting ``mm3_id``: ``hint`` (vault-relative) if given and correct,
    else the most recent entry of the Recent list that still holds that meeting."""
    if hint:
        path = confine(root, hint)
        if _matches(root, path, mm3_id):
            entries = [e for e in recents.for_meeting(mm3_id) if Path(e.note_path) == path]
            return path, entries[0] if entries else None
    for entry in recents.for_meeting(mm3_id):
        path = Path(entry.note_path)
        if _matches(root, path, mm3_id):
            return path.resolve(), entry
    raise not_found()


def find_job(runner: JobRunner, mm3_id: str, entry: RecentMeeting | None) -> str | None:
    """The job that produced the meeting (for its audio), if it still exists."""
    if entry is not None and entry.job_id and runner.jobs.find(entry.job_id) is not None:
        return entry.job_id
    for job in runner.jobs.list_jobs(None, limit=500):  # notes written before migration 3
        written = job_dir(runner.jobs_root, job.id) / WRITTEN_FILE
        if not written.is_file():
            continue
        try:
            if json.loads(written.read_text(encoding="utf-8")).get("mm3_id") == mm3_id:
                return job.id
        except (OSError, ValueError):
            continue
    return None


def audio_state(runner: JobRunner, job_id: str | None) -> tuple[AudioState, str]:
    """``(state, message)`` for the player."""
    if job_id is None:
        return "none", (
            "No recording is linked to this note (it was processed elsewhere, or its job was "
            "deleted). The transcript works without it."
        )
    try:
        runner.audio_file(job_id)
    except MM3Error as exc:
        state: AudioState = "expired" if exc.code == "E_AUDIO_EXPIRED" else "missing"
        return state, exc.message
    return "ok", ""


# -- transcript view -------------------------------------------------------------------------


@dataclass(frozen=True)
class WordView:
    start: float
    text: str


@dataclass(frozen=True)
class SegmentView:
    index: int
    start: float
    end: float
    text: str
    words: tuple[WordView, ...]


@dataclass(frozen=True)
class TurnView:
    label: str | None
    name: str
    colour: int | None
    start: float
    segments: tuple[SegmentView, ...]


@dataclass(frozen=True)
class SpeakerView:
    label: str
    name: str
    placeholder: bool
    colour: int


@dataclass(frozen=True)
class TranscriptView:
    turns: tuple[TurnView, ...]
    speakers: tuple[SpeakerView, ...]
    duration: float | None
    diarized: bool
    segment_count: int


def clock(seconds: float) -> str:
    total = int(max(seconds, 0))
    h, rest = divmod(total, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def transcript_view(doc: CompanionTranscript) -> TranscriptView:
    named = doc.named()
    labels = named.speaker_labels
    colours = {label: i % SPEAKER_COLOURS for i, label in enumerate(labels)}
    turns: list[TurnView] = []
    for index, seg in enumerate(named.segments):
        words = tuple(
            WordView(w.start if w.start is not None else seg.start, w.text)
            for w in seg.words
            if w.text.strip()
        )
        view = SegmentView(index, seg.start, seg.end, " ".join(seg.text.split()), words)
        if turns and turns[-1].label == seg.speaker_label:
            last = turns[-1]
            turns[-1] = TurnView(
                last.label, last.name, last.colour, last.start, (*last.segments, view)
            )
        else:
            turns.append(
                TurnView(
                    seg.speaker_label,
                    seg.speaker_name or "Speaker",
                    colours.get(seg.speaker_label) if seg.speaker_label else None,
                    seg.start,
                    (view,),
                )
            )
    speakers = tuple(
        SpeakerView(
            label,
            doc.speakers.display_name(label, labels),
            label not in doc.speakers.names,
            colours[label],
        )
        for label in sorted(labels, key=natural_key)
    )
    return TranscriptView(
        tuple(turns), speakers, named.duration, named.diarized, len(named.segments)
    )


# -- the workspace ---------------------------------------------------------------------------


@dataclass
class Workspace:
    mm3_id: str
    root: Path
    path: Path
    text: str
    sha: str
    doc: EditableDocument
    parsed: ParsedNote | None
    readonly_reason: str = ""
    companion_path: Path | None = None
    companion: ParsedTranscript | None = None
    transcript: TranscriptView | None = None
    job_id: str | None = None
    audio: AudioState = "none"
    audio_message: str = ""
    retention: RetentionStatus | None = None
    audio_pinned: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def relative(self) -> str:
        return self.path.relative_to(self.root).as_posix()

    @property
    def readonly(self) -> bool:
        return bool(self.readonly_reason)

    @property
    def can_regenerate(self) -> bool:
        return not self.readonly and self.companion is not None

    @property
    def damaged_ids(self) -> list[str]:
        """Section ids named by marker errors (candidates for "append as new section")."""
        if self.parsed is None:
            return []
        valid = {s.id for s in self.doc.sections}
        ids: list[str] = []
        for err in self.parsed.marker_errors:
            ids += [i for i in err.section_ids if i not in valid and i not in ids]
        return ids


def load_workspace(
    root: Path,
    path: Path,
    mm3_id: str,
    store: ReviewStore,
    runner: JobRunner | None,
    entry: RecentMeeting | None,
) -> Workspace:
    text = read_text(path)
    sha = store.put_base(text)
    doc = split_document(text)
    parsed: ParsedNote | None
    reason = ""
    try:
        parsed = parse_note(text)
    except NoteParseError as exc:
        parsed, reason = None, f"{exc.message} It is shown read-only."
    except MM3Error as exc:  # e.g. frontmatter that is not valid YAML
        parsed, reason = None, f"The note's properties cannot be read ({exc.message})."
    if parsed is not None and not doc.sections and not parsed.marker_errors:
        reason = (
            "This note has no MeetingMaster3 section markers, so there is nothing to regenerate. "
            "It is shown read-only; edit it in Obsidian."
        )
    ws = Workspace(mm3_id, root, path, text, sha, doc, parsed, readonly_reason=reason)
    if parsed is not None:
        ws.warnings = list(parsed.warnings)
        found = find_companion(path, parsed)
        if found is not None:
            ws.companion_path, ws.companion = found
            ws.transcript = transcript_view(found[1].doc)
            if not found[1].body_matches_data:
                ws.warnings.append(
                    "The readable transcript was edited by hand; the timings come from its "
                    "hidden data block, which was not changed."
                )
    if runner is not None:
        ws.job_id = find_job(runner, mm3_id, entry)
        ws.audio, ws.audio_message = audio_state(runner, ws.job_id)
        if ws.job_id is not None:
            ws.audio_pinned = runner.jobs.get(ws.job_id).audio_pinned
            ws.retention = runner.retention_status(runner.jobs.get(ws.job_id))
    return ws


def note_sha(path: Path) -> str:
    return text_sha(read_text(path))
