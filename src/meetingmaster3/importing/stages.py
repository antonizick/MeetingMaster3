"""The ``import`` job's own stages: ``import_parse`` and its ``await_speaker_confirmation``.

``import_parse`` reads the uploaded file (``source.<ext>`` in the job folder), writes the preview
(``import.json``: every turn with its speaker, time and confidence, and the speakers with their
default names) and the parsed transcript (``transcript.parsed.json``, its artifact).

The confirmation pauses the job until the user has checked who said each turn and named the
speakers. The answer is ``{"speakers": {label: name}, "turns": {"<index>": label}}``: names for
the speakers and the turns moved to another speaker. It writes the corrected transcript
(``transcript.imported.json``, which ``generate`` and ``write`` read), the job's speaker map and
``speakers.confirmed.json``. ``options.import_confirmed`` (``mm3 import --yes``) skips the pause.

A Grok share link (Phase 15l) has no upload: the job's ``options.import_share_id`` makes
``import_parse`` download the share first (cancellable, with progress) and keep it as
``source.json``, so a resume never downloads it again. The title, date and time the user left
empty (``options.import_fill``) are then taken from the conversation.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path, PurePath
from typing import Any

from meetingmaster3.domain.transcript import SPEAKER_LABEL_RE, SpeakerMap, Transcript, clean_name
from meetingmaster3.errors import MM3Error
from meetingmaster3.importing import grok_share
from meetingmaster3.importing.convert import LOW_CONFIDENCE, ImportSpeaker, to_transcript
from meetingmaster3.importing.detect import decode, detect_and_parse
from meetingmaster3.importing.fetch import fetch_share
from meetingmaster3.importing.model import ImportedConversation, empty, format_name
from meetingmaster3.jobs.stage import AwaitInputStage, BaseStage, InputRequired, StageContext
from meetingmaster3.speakers import cascade
from meetingmaster3.speakers.stages import CONFIRMED_FILE
from meetingmaster3.speakers.store import MAX_NAME_LENGTH
from meetingmaster3.storage.repositories import JobRepository
from meetingmaster3.vault.io import atomic_write_text

SOURCE_PREFIX = "source."
PREVIEW_FILE = "import.json"
PARSED_FILE = "transcript.parsed.json"
IMPORTED_TRANSCRIPT_FILE = "transcript.imported.json"
CONFIRM_KIND = "import_confirmation"
SOURCE_FORMAT_OPTION = "import_format"
CONFIRMED_OPTION = "import_confirmed"
SPEAKERS_OPTION = "import_speakers"
"""Job option ``{"user": "Nick", "assistant": "Grok"}`` (or ``{"SPEAKER_00": …}``): names to
use instead of the defaults (``mm3 import --speaker``)."""
SHARE_OPTION = "import_share_id"
"""Job option: the id of the Grok share to download (never a URL; Phase 15l)."""
FILL_OPTION = "import_fill"
"""Job option: the details (``title``, ``meeting_date``, ``meeting_time``) the user left empty,
filled from the downloaded conversation."""
SHARE_SOURCE = SOURCE_PREFIX + "json"
SHARE_SOURCE_NAME = "Grok share link"
"""The job's ``source_filename`` for a share link (the link itself is not kept)."""
SHARE_PLACEHOLDER_TITLE = "Grok conversation"
FILLABLE = ("title", "meeting_date", "meeting_time")


def find_source(job_dir: Path) -> Path | None:
    found = sorted(p for p in job_dir.glob(SOURCE_PREFIX + "*") if p.is_file())
    return found[0] if found else None


def source_file(job_dir: Path) -> Path:
    found = find_source(job_dir)
    if found is None:
        raise MM3Error(
            "E_IMPORT_MISSING",
            "The imported file of this job is missing.",
            "Import the file again.",
            status_code=409,
        )
    return found


def parse_upload(data: bytes, filename: str, settings: Any) -> ImportedConversation:
    return detect_and_parse(data, filename, max_bytes=settings.importing.max_mb * 1024 * 1024)


def parse_share_source(data: bytes, settings: Any) -> ImportedConversation:
    """A downloaded share is always read as one (never detected as some other format)."""
    text = decode(data, max_bytes=settings.importing.max_mb * 1024 * 1024)
    conv = grok_share.parse_share(text, SHARE_SOURCE)
    if not conv.turns:
        raise empty()
    return conv


IMPORT_EXTENSIONS = frozenset({"md", "markdown", "txt", "text", "vtt", "srt"})


def stored_name(filename: str | None) -> str:
    """``source.<ext>`` for an allowlisted text extension, ``source.txt`` otherwise (the parser
    reads the content, not the name)."""
    name = PurePath((filename or "").replace("\\", "/")).name
    _, dot, ext = name.rpartition(".")
    ext = ext.lower()
    return SOURCE_PREFIX + (ext if dot and ext in IMPORT_EXTENSIONS else "txt")


def import_defaults(conv: ImportedConversation) -> dict[str, Any]:
    """Title and date from the file itself (its heading, frontmatter or export header)."""
    out: dict[str, Any] = {"title": conv.title}
    if conv.started_at is not None:
        out["meeting_date"] = conv.started_at.date().isoformat()
        if conv.started_at.time() != dt.time(0):
            out["meeting_time"] = conv.started_at.time().replace(microsecond=0).isoformat()
    return out


def import_duration(conv: ImportedConversation) -> float | None:
    if not conv.timed:
        return None
    return max((t.end if t.end is not None else t.start or 0.0) for t in conv.turns)


def _named_overrides(options: dict[str, Any]) -> dict[str, str]:
    raw = options.get(SPEAKERS_OPTION) or {}
    if not isinstance(raw, dict):
        return {}
    return {str(k): clean_name(str(v)) for k, v in raw.items() if clean_name(str(v))}


def preview(
    conv: ImportedConversation, transcript: Transcript, speakers: list[ImportSpeaker]
) -> dict[str, Any]:
    """The content of ``import.json`` (read by the confirmation page)."""
    return {
        "format": conv.source_format,
        "format_name": format_name(conv.source_format),
        "title": conv.title,
        "started_at": conv.started_at.isoformat() if conv.started_at else None,
        "timed": transcript.timed,
        "warnings": conv.warnings,
        "speakers": [s.to_dict() for s in speakers],
        "turns": [
            {
                "index": seg.id,
                "label": seg.speaker_label,
                "role": turn.role,
                "text": turn.text,
                "start": seg.start if transcript.timed else None,
                "confidence": turn.confidence,
                "low": turn.confidence < LOW_CONFIDENCE,
            }
            for seg, turn in zip(transcript.segments, conv.turns, strict=True)
        ],
    }


def share_options(data: dict[str, Any], share_id: str) -> dict[str, Any]:
    """Options for a share-link import: the share id, which details to fill from the
    conversation, and a placeholder title until it is downloaded."""
    out = dict(data)
    out[SHARE_OPTION] = share_id
    out[FILL_OPTION] = [k for k in FILLABLE if not out.get(k)]
    if not out.get("title"):
        out["title"] = SHARE_PLACEHOLDER_TITLE
    return out


def download_share(ctx: StageContext, share_id: str) -> Path:
    """Download the share into ``source.json`` (atomically, so a cancelled download leaves
    nothing to resume from)."""
    ctx.progress(None, "Downloading the conversation from grok.com")
    data = fetch_share(
        share_id,
        max_bytes=ctx.settings.importing.max_mb * 1024 * 1024,
        check=ctx.check_cancelled,
        sleep=ctx.sleep,
    )
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise grok_share.unavailable("Grok's answer is not readable text.") from exc
    return atomic_write_text(ctx.job_dir / SHARE_SOURCE, text, overwrite=True)


def fill_details(ctx: StageContext, conv: ImportedConversation) -> None:
    """Put the conversation's title, date and time where the user left them empty, in the
    options and in the job's row (the job list and the note read them)."""
    fill = [k for k in ctx.options.get(FILL_OPTION) or [] if k in FILLABLE]
    found = import_defaults(conv)
    changed = {k: found[k] for k in fill if found.get(k)}
    ctx.options.update(changed)
    row: dict[str, Any] = {"duration_seconds": import_duration(conv)}
    if "title" in changed:
        row["title"] = changed["title"]
    if "meeting_date" in changed:
        row["meeting_date"] = dt.date.fromisoformat(changed["meeting_date"])
    if ctx.db is not None:
        JobRepository(ctx.db).update(ctx.job_id, **row)


class ImportParseStage(BaseStage):
    name = "import_parse"
    display_name = "Reading the file"

    def run(self, ctx: StageContext) -> Path:
        settings = ctx.settings
        share_id = ctx.options.get(SHARE_OPTION)
        path = find_source(ctx.job_dir)
        if path is None and isinstance(share_id, str) and share_id:
            path = download_share(ctx, share_id)
        path = path or source_file(ctx.job_dir)
        ctx.check_cancelled()
        ctx.progress(0.1, "Reading the file")
        try:
            data = path.read_bytes()
            if share_id:
                conv = parse_share_source(data, settings)
            else:
                conv = parse_upload(data, ctx.job.source_filename or path.name, settings)
        except MM3Error:
            if share_id:  # not a share we can read: a resume downloads it again
                path.unlink(missing_ok=True)
            raise
        if share_id:
            fill_details(ctx, conv)
        names = _named_overrides(ctx.options)
        participants = [p for p in ctx.options.get("participants") or [] if isinstance(p, str)]
        user_name = names.get("user") or (participants[0] if participants else "")
        transcript, speakers = to_transcript(
            conv,
            user_name=user_name or settings.importing.user_name,
            assistant_name=names.get("assistant") or "AI",
        )
        speakers = [
            ImportSpeaker(s.label, s.role, s.detected, names[s.label]) if s.label in names else s
            for s in speakers
        ]
        for warning in conv.warnings:
            ctx.warn(warning)
        ctx.options[SOURCE_FORMAT_OPTION] = conv.source_format
        ctx.write_json(PREVIEW_FILE, preview(conv, transcript, speakers))
        # A re-run makes any earlier confirmation stale.
        (ctx.job_dir / IMPORTED_TRANSCRIPT_FILE).unlink(missing_ok=True)
        path = ctx.artifact(PARSED_FILE)
        path.write_text(transcript.model_dump_json(indent=2) + "\n", encoding="utf-8")
        ctx.progress(1.0, f"{len(transcript.segments)} turns read")
        return path


def _invalid(message: str) -> MM3Error:
    return MM3Error(
        "E_INPUT_INVALID",
        message,
        'Send {"speakers": {"<label>": "<name>"}, "turns": {"<turn index>": "<label>"}}.',
        status_code=422,
    )


def normalise_answer(data: dict[str, Any]) -> dict[str, Any]:
    """Check the shape of an answer: names for labels, labels for turn indexes."""
    speakers = data.get("speakers", {})
    turns = data.get("turns", {})
    if not isinstance(speakers, dict) or not isinstance(turns, dict):
        raise _invalid("The answer needs a speakers object and a turns object.")
    if len(speakers) > 200 or len(turns) > 100_000:
        raise _invalid("Too many speakers or turns.")
    names: dict[str, str] = {}
    for label, value in speakers.items():
        name = value.get("name") if isinstance(value, dict) else value
        if not isinstance(label, str) or not SPEAKER_LABEL_RE.match(label):
            raise _invalid(f"{str(label)[:64]!r} is not a speaker label.")
        if not isinstance(name, str) or not clean_name(name) or len(name) > MAX_NAME_LENGTH:
            raise _invalid(f"Speaker {label!r} needs a name of 1 to {MAX_NAME_LENGTH} characters.")
        names[label] = clean_name(name)
    moved: dict[str, str] = {}
    for index, label in turns.items():
        if not isinstance(index, str) or not index.isdigit():
            raise _invalid(f"{str(index)[:16]!r} is not a turn number.")
        if not isinstance(label, str) or not SPEAKER_LABEL_RE.match(label):
            raise _invalid(f"Turn {index}: {str(label)[:64]!r} is not a speaker label.")
        moved[str(int(index))] = label
    return {"speakers": names, "turns": moved}


def check_answer(answer: dict[str, Any], preview_data: dict[str, Any]) -> None:
    """Every label and turn of ``answer`` exists in the job's preview (422 otherwise)."""
    labels = {s["label"] for s in preview_data.get("speakers", [])}
    count = len(preview_data.get("turns", []))
    for label in answer["speakers"]:
        if label not in labels:
            raise _invalid(f"This conversation has no speaker {label!r}.")
    for index, label in answer["turns"].items():
        if int(index) >= count:
            raise _invalid(f"This conversation has no turn {index}.")
        if label not in labels:
            raise _invalid(f"Turn {index}: this conversation has no speaker {label!r}.")


def read_preview(job_dir: Path) -> dict[str, Any]:
    path = job_dir / PREVIEW_FILE
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


class ImportConfirmationStage(AwaitInputStage):
    """Check who said each turn and name the speakers (the import's "Name speakers" step)."""

    def __init__(self) -> None:
        super().__init__("await_speaker_confirmation", "Check the speakers", CONFIRM_KIND)

    def payload(self, ctx: StageContext) -> dict[str, Any]:
        data = read_preview(ctx.job_dir)
        turns = data.get("turns", [])
        return {
            "format": data.get("format"),
            "format_name": data.get("format_name"),
            "turns": len(turns),
            "low_confidence": sum(1 for t in turns if t.get("low")),
            "speakers": data.get("speakers", []),
        }

    def validate_input(self, data: dict[str, Any]) -> dict[str, Any]:
        return normalise_answer(data)

    def run(self, ctx: StageContext) -> Path:
        parsed = Transcript.model_validate_json(
            ctx.artifacts["import_parse"].read_text(encoding="utf-8")
        )
        answer = ctx.input()
        if answer is None:
            if not (ctx.options.get(CONFIRMED_OPTION) is True or not parsed.speaker_labels):
                raise InputRequired(self.kind, self.payload(ctx))
            answer = {"speakers": {}, "turns": {}}
        answer = normalise_answer(answer)
        data = read_preview(ctx.job_dir)
        known = {s["label"]: s for s in data.get("speakers", [])}
        moved = {int(i): label for i, label in answer["turns"].items() if label in known}
        if len(moved) != len(answer["turns"]):
            ctx.warn("Ignored changes that name an unknown speaker.")
        segments = [
            s.model_copy(update={"speaker_label": moved[s.id]}) if s.id in moved else s
            for s in parsed.segments
        ]
        final = parsed.model_copy(update={"segments": segments})
        used = set(final.speaker_labels)
        names = {
            label: answer["speakers"].get(label) or s.get("default_name") or ""
            for label, s in known.items()
            if label in used
        }
        speaker_map = SpeakerMap(names={k: v for k, v in names.items() if v})
        path = ctx.artifact(IMPORTED_TRANSCRIPT_FILE)
        path.write_text(final.model_dump_json(indent=2) + "\n", encoding="utf-8")
        cascade.save_job_speakers(ctx.job_dir, speaker_map, final)
        labels = final.speaker_labels
        return ctx.write_json(
            CONFIRMED_FILE,
            {
                "speakers": {
                    label: {"name": name, "person_id": None, "enroll": False}
                    for label, name in speaker_map.names.items()
                },
                "speaker_map": speaker_map.names,
                "participants": cascade.speaker_names(speaker_map, labels),
                "moved_turns": len(moved),
                "enrolled": [],
            },
        )
