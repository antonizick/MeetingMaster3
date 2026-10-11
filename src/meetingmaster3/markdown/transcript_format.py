"""Companion transcript (``YYYY-MM-DD - Title.transcript.md``): writer and parser.

Layout::

    ---
    mm3-version: 1
    mm3-id: <uuid>
    mm3-note: "[[2026-10-11 - Product Sync]]"
    mm3-speakers:
      SPEAKER_00: Alice
    duration: "0:42:17"
    language: en
    mm3-transcription-model: large-v3-turbo
    mm3-diarized: true
    ---
    # Transcript: Product Sync

    **[00:00:01] Alice:** Good morning, everyone.

    **[00:00:09] SPEAKER_01's name:** ...

    <!-- mm3:transcript-data v1
    {"language":"en","duration":2537.4,"model":"large-v3-turbo","diarized":true}
    {"id":0,"start":1.02,"end":8.7,"label":"SPEAKER_00","text":"...","words":[[1.02,1.4,0.97,"Good"]]}
    -->

The readable turns are for people. The data block (one hidden HTML comment at the end, one JSON
object per line) is the lossless machine copy and the source of truth for segments, words,
timings and labels (ADR-0009). Names live only in ``mm3-speakers`` and the visible turn
headings, so renaming a speaker rewrites those and never touches the data.
"""

from __future__ import annotations

import json
import math
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from meetingmaster3.domain.transcript import (
    TRANSCRIPT_KEYS,
    CompanionTranscript,
    Segment,
    SpeakerMap,
    Transcript,
    Word,
    group_turns,
)
from meetingmaster3.errors import MM3Error
from meetingmaster3.markdown.frontmatter import (
    ParsedFrontmatter,
    parse_wikilink,
    render_frontmatter,
    same,
    split_frontmatter,
    wikilink,
)
from meetingmaster3.markdown.note_parser import BOM, meeting_id, speakers_value
from meetingmaster3.markdown.sections import detect_newline

DATA_VERSION = 1
TITLE_PREFIX = "Transcript: "
_DATA_RE = re.compile(
    r"^<!-- mm3:transcript-data v(?P<v>\d+)[ \t]*\r?\n(?P<data>.*?)^-->[ \t]*(?:\r?\n|$)",
    re.M | re.S,
)
_TURN_RE = re.compile(
    r"^\*\*\[(?P<h>\d+):(?P<m>[0-5]\d):(?P<s>[0-5]\d)\] (?P<name>.+?):\*\*"
    r"(?: (?P<text>.*?))?[ \t]*\r?$",
    re.M,
)
_H1_RE = re.compile(r"^# (?P<title>.+?)[ \t]*\r?$", re.M)


class TranscriptParseError(MM3Error):
    pass


def timestamp(seconds: float) -> str:
    """``[hh:mm:ss]`` text for a time in seconds (floored)."""
    total = math.floor(max(seconds, 0.0))
    return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"


def duration_text(seconds: float) -> str:
    total = round(seconds)
    return f"{total // 3600}:{total % 3600 // 60:02d}:{total % 60:02d}"


@dataclass(frozen=True)
class VisibleTurn:
    """A turn as it appears in the readable part of the file (possibly edited by the user)."""

    start: int
    """Seconds, from the ``[hh:mm:ss]`` stamp."""
    name: str
    text: str
    name_start: int
    name_end: int
    """Offsets of the name in the body text."""


@dataclass(frozen=True)
class ParsedTranscript:
    doc: CompanionTranscript
    frontmatter: ParsedFrontmatter
    visible_turns: tuple[VisibleTurn, ...]
    body_matches_data: bool
    """``False`` if the readable turns no longer match the data block (the user edited them)."""
    warnings: tuple[str, ...] = ()
    bom: bool = False
    body: str = field(default="", repr=False)


# --- data block ---------------------------------------------------------------------------


def _json_line(obj: Any) -> str:
    # ASCII-only, and no '<' or '>' so the text can never close the HTML comment early.
    text = json.dumps(obj, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
    return text.replace("<", "\\u003c").replace(">", "\\u003e")


def render_data_block(transcript: Transcript, newline: str = "\n") -> str:
    header = {
        "language": transcript.language,
        "duration": transcript.duration,
        "model": transcript.model,
        "diarized": transcript.diarized,
    }
    lines = [f"<!-- mm3:transcript-data v{DATA_VERSION}", _json_line(header)]
    for s in transcript.segments:
        lines.append(
            _json_line(
                {
                    "id": s.id,
                    "start": s.start,
                    "end": s.end,
                    "label": s.speaker_label,
                    "text": s.text,
                    "words": [[w.start, w.end, w.score, w.text] for w in s.words],
                }
            )
        )
    lines.append("-->")
    return newline.join(lines) + newline


def _data_error(message: str) -> TranscriptParseError:
    return TranscriptParseError(
        "transcript_data_invalid",
        f"The transcript's hidden data block is damaged: {message}.",
        "Restore the file from a backup or the archive, or re-transcribe the audio if it is "
        "still kept. The readable text is unaffected.",
    )


def parse_data_block(body: str) -> Transcript:
    matches = list(_DATA_RE.finditer(body))
    if not matches:
        raise TranscriptParseError(
            "transcript_data_missing",
            "This transcript has no MeetingMaster3 data block, so timings cannot be recovered.",
            "Re-transcribe the audio if it is still kept; the note itself is unaffected.",
        )
    m = matches[-1]
    if int(m["v"]) != DATA_VERSION:
        raise _data_error(f"unsupported data version {m['v']}")
    lines = [ln for ln in m["data"].replace("\r\n", "\n").split("\n") if ln.strip()]
    try:
        records = [json.loads(ln) for ln in lines]
        header, rows = records[0], records[1:]
        segments = [
            Segment(
                id=r["id"],
                start=r["start"],
                end=r["end"],
                speaker_label=r.get("label"),
                text=r["text"],
                words=[Word(start=w[0], end=w[1], score=w[2], text=w[3]) for w in r["words"]],
            )
            for r in rows
        ]
        return Transcript(
            segments=segments,
            language=header.get("language"),
            duration=header.get("duration"),
            model=header.get("model"),
            diarized=bool(header.get("diarized", False)),
        )
    except (ValueError, KeyError, IndexError, TypeError, ValidationError) as exc:
        raise _data_error(type(exc).__name__) from exc


# --- readable body ------------------------------------------------------------------------


def _turn_lines(doc: CompanionTranscript) -> list[str]:
    labels = doc.transcript.speaker_labels
    lines = []
    for turn in group_turns(doc.transcript):
        name = doc.speakers.display_name(turn.speaker_label, labels)
        lines.append(f"**[{timestamp(turn.start)}] {name}:** {turn.text}".rstrip())
    return lines


def render_body(doc: CompanionTranscript) -> str:
    nl = doc.newline
    parts = [f"# {TITLE_PREFIX}{doc.title}{nl}{nl}"]
    turns = _turn_lines(doc)
    parts.extend(t + nl + nl for t in turns)
    if not turns:
        parts.append(f"_No speech was detected._{nl}{nl}")
    parts.append(render_data_block(doc.transcript, nl))
    return "".join(parts)


def _visible_turns(body: str) -> list[VisibleTurn]:
    data = _DATA_RE.search(body)
    end = data.start() if data else len(body)
    return [
        VisibleTurn(
            start=int(m["h"]) * 3600 + int(m["m"]) * 60 + int(m["s"]),
            name=m["name"],
            text=m["text"] or "",
            name_start=m.start("name"),
            name_end=m.end("name"),
        )
        for m in _TURN_RE.finditer(body, 0, end)
    ]


# --- frontmatter --------------------------------------------------------------------------


def _yaml_value(key: str, doc: CompanionTranscript) -> Any:
    t = doc.transcript
    return {
        "mm3-version": doc.format_version,
        "mm3-id": str(doc.meeting_id),
        "mm3-note": wikilink(doc.note_ref) if doc.note_ref else None,
        "mm3-speakers": dict(doc.speakers.names) or None,
        "duration": duration_text(t.duration) if t.duration is not None else None,
        "language": t.language,
        "mm3-transcription-model": t.model,
        "mm3-diarized": t.diarized,
    }[key]


def _frontmatter_data(doc: CompanionTranscript, base: ParsedTranscript | None) -> dict[str, Any]:
    if base is None:
        data = {k: v for k in TRANSCRIPT_KEYS if (v := _yaml_value(k, doc)) is not None}
        data.update(doc.extra_properties)
        return data
    items: list[tuple[str, Any]] = []
    for key, raw in base.frontmatter.data.items():
        if key in TRANSCRIPT_KEYS:
            v = _yaml_value(key, doc)
            if v == _yaml_value(key, base.doc):
                items.append((key, raw))
            elif v is not None:
                items.append((key, v))
        elif key in doc.extra_properties:
            v = doc.extra_properties[key]
            items.append((key, raw if same(v, raw) else v))
    present = {k for k, _ in items}
    for key in TRANSCRIPT_KEYS:
        v = _yaml_value(key, doc)
        if key not in present and key not in base.frontmatter.data and v is not None:
            items.append((key, v))
    present = {k for k, _ in items}
    items.extend((k, v) for k, v in doc.extra_properties.items() if k not in present)
    return dict(items)


# --- public API ---------------------------------------------------------------------------


def parse_transcript(text: str) -> ParsedTranscript:
    bom = text.startswith(BOM)
    if bom:
        text = text[1:]
    fm, body = split_frontmatter(text)
    if fm is None:
        raise TranscriptParseError(
            "not_an_mm3_transcript",
            "This file has no frontmatter, so it is not a MeetingMaster3 transcript.",
            "Choose the '.transcript.md' file written next to the note.",
        )
    warnings: list[str] = []
    transcript = parse_data_block(body)
    h1 = _H1_RE.search(body)
    title = h1["title"].removeprefix(TITLE_PREFIX) if h1 else ""
    version = fm.data.get("mm3-version", 1)
    doc = CompanionTranscript(
        meeting_id=meeting_id(fm.data),
        title=title,
        note_ref=parse_wikilink(fm.data.get("mm3-note")),
        transcript=transcript,
        speakers=speakers_value(fm.data.get("mm3-speakers"), warnings),
        extra_properties={k: v for k, v in fm.data.items() if k not in TRANSCRIPT_KEYS},
        format_version=version if isinstance(version, int) and not isinstance(version, bool) else 1,
        newline=detect_newline(text),
    )
    visible = _visible_turns(body)
    expected = _turn_lines(doc)
    actual = [body[_line_bounds(body, v.name_start)] for v in visible]
    return ParsedTranscript(
        doc=doc,
        frontmatter=fm,
        visible_turns=tuple(visible),
        body_matches_data=[a.rstrip("\r") for a in actual] == expected,
        warnings=tuple(warnings),
        bom=bom,
        body=body,
    )


def _line_bounds(text: str, index: int) -> slice:
    start = text.rfind("\n", 0, index) + 1
    end = text.find("\n", index)
    return slice(start, len(text) if end < 0 else end)


def _renamed_body(doc: CompanionTranscript, base: ParsedTranscript) -> str:
    turns = group_turns(doc.transcript)
    if len(turns) != len(base.visible_turns):
        raise MM3Error(
            "transcript_turns_mismatch",
            "The readable transcript no longer matches its data (turns were added, removed or "
            "merged), so speaker names cannot be updated in place.",
            "Re-render the transcript from its data (edits to the readable text are replaced), "
            "or rename the speakers by hand.",
            status_code=409,
        )
    labels = doc.transcript.speaker_labels
    out, pos = [], 0
    for turn, visible in zip(turns, base.visible_turns, strict=True):
        out.append(base.body[pos : visible.name_start])
        out.append(doc.speakers.display_name(turn.speaker_label, labels))
        pos = visible.name_end
    out.append(base.body[pos:])
    return "".join(out)


def render_transcript(
    doc: CompanionTranscript, base: ParsedTranscript | None = None, *, rerender: bool = False
) -> str:
    """Render a companion transcript.

    With ``base`` (the parsed file on disk), unchanged frontmatter keys and the unchanged body
    are reused byte-for-byte. If only the speaker names changed, just the names in the turn
    headings are rewritten, so the user's edits to the readable text survive. ``rerender=True``
    rebuilds the body from the data instead.
    """
    fm = render_frontmatter(
        _frontmatter_data(doc, base),
        newline=doc.newline,
        base=base.frontmatter if base else None,
    )
    if base is None or rerender:
        body = render_body(doc)
    elif doc.transcript == base.doc.transcript and doc.title == base.doc.title:
        body = base.body if doc.speakers == base.doc.speakers else _renamed_body(doc, base)
    else:
        body = render_body(doc)
    return (BOM if base and base.bom else "") + fm + body


def build_companion(
    meeting_id: uuid.UUID,
    title: str,
    transcript: Transcript,
    speakers: SpeakerMap,
    *,
    note_ref: str | None = None,
    newline: str = "\n",
) -> CompanionTranscript:
    return CompanionTranscript(
        meeting_id=meeting_id,
        title=title,
        note_ref=note_ref,
        transcript=transcript,
        speakers=speakers,
        newline="\r\n" if newline == "\r\n" else "\n",
    )


def rename_speakers(text: str, speakers: SpeakerMap) -> str:
    """Rewrite a companion file's speaker names (frontmatter and turn headings); labels and
    the data block are unchanged."""
    parsed = parse_transcript(text)
    return render_transcript(parsed.doc.model_copy(update={"speakers": speakers}), parsed)
