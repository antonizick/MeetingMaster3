"""Export a meeting's files and the app's own data (data ownership, design notes MVP item 7).

Everything is built in memory (a meeting is a few hundred kB; the audio is Opus at ~11 MB/hour)
and nothing leaves the machine. The export of all app data never contains secrets (the settings
are written masked) nor voiceprint embeddings (biometric data; delete or keep them in the app).
"""

from __future__ import annotations

import datetime as dt
import io
import json
import re
import zipfile
from pathlib import Path
from typing import Any

from meetingmaster3.config.settings import Settings
from meetingmaster3.errors import MM3Error
from meetingmaster3.jobs.files import EMBEDDINGS_NAME
from meetingmaster3.markdown.readable_transcript import clock
from meetingmaster3.markdown.transcript_format import TranscriptParseError, parse_transcript
from meetingmaster3.storage.db import Database
from meetingmaster3.vault.io import read_text
from meetingmaster3.vault.naming import TRANSCRIPT_SUFFIX
from meetingmaster3.vault.paths import confine, is_inside
from meetingmaster3.vault.picker import read_identity

KINDS = ("note", "transcript", "txt", "zip")
#: Tables included in "Export all app data". Voiceprint tables are deliberately absent.
EXPORT_TABLES = ("jobs", "job_stages", "recent_meetings", "feedback")
ARTIFACT_SUFFIXES = (".json", ".md", ".txt", ".srt", ".vtt")
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
_UNSAFE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def safe_filename(name: str) -> str:
    cleaned = _UNSAFE.sub("_", name).strip(" .") or "meeting"
    return cleaned[:150]


def _not_found(what: str) -> MM3Error:
    return MM3Error(
        "E_NOTE_NOT_FOUND",
        f"{what} was not found in the vault.",
        "Open it from the Meetings page, or check that the file was not moved.",
        status_code=404,
    )


def locate(vault_root: Path, note_relative: str) -> tuple[Path, Path | None]:
    """The note and its companion transcript (``None`` if there is none), both confined to the
    vault."""
    if not note_relative.endswith(".md") or note_relative.endswith(TRANSCRIPT_SUFFIX):
        raise MM3Error(
            "E_NOTE_NOT_FOUND",
            "That is not a note file.",
            "Give the vault-relative path of the note (.md), not of its transcript.",
            status_code=404,
        )
    note = confine(vault_root, note_relative)
    if not note.is_file():
        raise _not_found("The note")
    info = read_identity(note)
    if info is not None and info.is_readable:
        raise MM3Error(
            "E_NOTE_NOT_FOUND",
            "That is the readable transcript, not a note.",
            "Give the vault-relative path of the note (.md) next to it.",
            status_code=404,
        )
    companion = note.with_name(note.name.removesuffix(".md") + TRANSCRIPT_SUFFIX)
    transcript = companion if companion.is_file() and is_inside(vault_root, companion) else None
    return note, transcript


def transcript_to_text(markdown: str) -> str:
    """The readable turns of a companion transcript as plain text, laid out like the readable
    transcript (R25): the time and the name on one line, the text below, a blank line between
    turns."""
    try:
        parsed = parse_transcript(markdown)
    except TranscriptParseError:
        return markdown
    blocks = []
    timed = parsed.doc.transcript.timed
    for turn in parsed.visible_turns:
        text = " ".join(turn.text.split())
        head = f"{clock(turn.start)} {turn.name}" if timed else turn.name
        blocks.append(head + (f"\n{text}" if text else ""))
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def meeting_zip(
    note: Path,
    transcript: Path | None,
    audio: Path | None = None,
    *,
    audio_name: str = "",
    readable: Path | None = None,
) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(note.name, read_text(note))
        if readable is not None and readable.is_file():
            archive.writestr(readable.name, read_text(readable))
        if transcript is not None:
            archive.writestr(transcript.name, read_text(transcript))
            archive.writestr(
                transcript.name.removesuffix(".md") + ".txt",
                transcript_to_text(read_text(transcript)),
            )
        if audio is not None and audio.is_file():
            archive.write(audio, audio_name or f"{note.stem}{audio.suffix}")
    return buffer.getvalue()


def _json_default(value: Any) -> Any:
    if isinstance(value, bytes):
        return None
    return str(value)


def dump_table(db: Database, table: str) -> list[dict[str, Any]]:
    if table not in EXPORT_TABLES:  # table names are never user input; keep it that way
        raise ValueError(table)
    return [dict(row) for row in db.fetchall(f"SELECT * FROM {table}")]  # noqa: S608


def export_all(db: Database, settings: Settings, jobs_root: Path) -> bytes:
    """A zip with the settings (secrets masked), the database tables as JSON and each job's
    small artifacts (transcript JSON, drafts, speaker maps...). Audio is not included."""
    buffer = io.BytesIO()
    now = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "README.txt",
            f"MeetingMaster3 data export, {now}.\n"
            "settings.json has every secret masked. Voiceprints and audio are not included.\n",
        )
        archive.writestr("settings.json", json.dumps(settings.dump_masked(), indent=2))
        for table in EXPORT_TABLES:
            archive.writestr(
                f"database/{table}.json",
                json.dumps(dump_table(db, table), indent=2, default=_json_default),
            )
        if jobs_root.is_dir():
            for folder in sorted(p for p in jobs_root.iterdir() if p.is_dir()):
                for file in sorted(folder.rglob("*")):
                    if (
                        file.is_file()
                        and not file.is_symlink()
                        and file.suffix.lower() in ARTIFACT_SUFFIXES
                        and file.name != EMBEDDINGS_NAME  # biometric (S7): never exported
                        and file.stat().st_size <= MAX_ARTIFACT_BYTES
                    ):
                        archive.write(file, f"jobs/{folder.name}/{file.relative_to(folder)}")
    return buffer.getvalue()
