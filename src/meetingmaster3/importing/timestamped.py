"""Parsers for transcripts that carry times: ``[hh:mm:ss] Name: text`` lines, the MM3 ``.txt``
export (``00:01 Alice`` then the text), MM3 companion ``.transcript.md`` files, WebVTT and SubRip.

Times are kept. Consecutive cues of the same speaker merge into one turn, up to
:data:`MERGE_SECONDS` long, so a caption file with no speaker names still keeps its timing in
steps a reader can click.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from meetingmaster3.importing.model import ImportedConversation, ImportedTurn, Role, unreadable

MERGE_SECONDS = 60.0

_TIME = r"(?:(?P<h>\d{1,2}):)?(?P<m>\d{1,2}):(?P<s>[0-5]\d)(?:[.,](?P<f>\d{1,3}))?"
_NAME = r"[^\s:\[\]*][^:\n\[\]*]{0,59}?"
# [00:01:02] Alice: text · **[00:01:02] Alice:** text · [00:01] text
_INLINE = re.compile(
    rf"^\s*(?:\*\*)?\[{_TIME}\]\s*(?:(?P<name>{_NAME}):(?:\*\*)?)?(?:\*\*)?[ \t]*(?P<text>.*?)\s*$"
)
# 00:01 Alice  (the MM3 .txt export and the readable transcript: time then name, text below)
_HEAD_TIME_FIRST = re.compile(rf"^\s*{_TIME}[ \t]+(?P<name>[^\d\s][^\n,;!?]{{0,59}}?)\s*$")
# Alice  00:01:02   or   Alice (00:01:02)   (Otter, Plaud and similar)
_HEAD_NAME_FIRST = re.compile(rf"^\s*(?P<name>[^\d\s][^\n,;!?]{{0,59}}?)[ \t]+\(?{_TIME}\)?\s*$")
MAX_NAME_WORDS = 6
"""A "name" longer than this is a sentence, not a speaker."""
_H1 = re.compile(r"^#\s+(?P<title>.+?)\s*#*\s*$")
_CUE_TIME = re.compile(
    r"^\s*(?P<a>(?:\d{1,2}:)?\d{1,2}:[0-5]\d[.,]\d{1,3})\s+-->\s+"
    r"(?P<b>(?:\d{1,2}:)?\d{1,2}:[0-5]\d[.,]\d{1,3})"
)
_VOICE = re.compile(r"<v(?:\.[^\s>]*)?\s+(?P<name>[^>]+)>")
_TAG = re.compile(r"</?[^>\n]{0,200}>")
_PREFIX_NAME = re.compile(r"^(?:-\s*)?(?P<name>[A-Z][\w .'-]{0,39}?):\s+(?P<text>\S.*)$")


def seconds(h: str | None, m: str, s: str, f: str | None = None) -> float:
    value = int(h or 0) * 3600 + int(m) * 60 + int(s)
    return value + (int(f.ljust(3, "0")) / 1000 if f else 0.0)


def _clock(text: str) -> float:
    parts = text.replace(",", ".").split(":")
    whole, _, frac = parts[-1].partition(".")
    h = parts[0] if len(parts) == 3 else None
    return seconds(h, parts[-2], whole, frac or None)


@dataclass
class _Cue:
    speaker: str
    start: float
    end: float | None
    text: list[str] = field(default_factory=list)


def _clean_name(name: str) -> str:
    return " ".join(name.replace("*", "").split()).strip()


def merge(cues: list[_Cue], role: Role | None = "other") -> list[ImportedTurn]:
    """Consecutive cues of one speaker → turns (at most :data:`MERGE_SECONDS` long). A cue's end
    is its own end when the file gives one, else the next cue's start."""
    turns: list[ImportedTurn] = []
    current: _Cue | None = None
    cues = [c for c in cues if " ".join(c.text).strip()]
    for i, cue in enumerate(cues):
        end = cue.end
        if end is None:
            end = cues[i + 1].start if i + 1 < len(cues) else cue.start
        end = max(end, cue.start)
        if (
            current is not None
            and current.speaker == cue.speaker
            and cue.start - current.start < MERGE_SECONDS
        ):
            current.text.append(" ".join(cue.text))
            current.end = max(current.end or end, end)
            continue
        if current is not None:
            turns.append(_turn(current, role))
        current = _Cue(cue.speaker, cue.start, end, [" ".join(cue.text)])
    if current is not None:
        turns.append(_turn(current, role))
    return turns


def _turn(cue: _Cue, role: Role | None) -> ImportedTurn:
    text = " ".join(" ".join(cue.text).split())
    return ImportedTurn(
        speaker=cue.speaker,
        role=role if cue.speaker else None,
        text=text,
        start=cue.start,
        end=cue.end,
    )


# -- [hh:mm:ss] Name: lines and time/name header lines ----------------------------------------


def _is_name(name: str) -> bool:
    return 0 < len(name.split()) <= MAX_NAME_WORDS and not name.endswith(".")


def _line_cue(line: str) -> tuple[_Cue, bool] | None:
    """A cue started by this line, and whether its text continues on the next lines."""
    m = _INLINE.match(line)
    if m:
        start = seconds(m["h"], m["m"], m["s"], m["f"])
        name, text = _clean_name(m["name"] or ""), m["text"]
        if name and not _is_name(name):  # "[00:01] A sentence: with a colon"
            name, text = "", f"{m['name']}: {text}".strip()
        return _Cue(name, start, None, [text] if text else []), False
    for pattern in (_HEAD_TIME_FIRST, _HEAD_NAME_FIRST):
        m = pattern.match(line)
        if m and _is_name(name := _clean_name(m["name"])):
            return _Cue(name, seconds(m["h"], m["m"], m["s"], m["f"]), None), True
    return None


def timestamped_score(text: str) -> float:
    """Share of the non-blank lines that start a timed cue (0 when fewer than two do)."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    starts = sum(1 for ln in lines if _line_cue(ln) is not None)
    return starts / len(lines) if lines and starts >= 2 else 0.0


def parse_timestamped(text: str, filename: str) -> ImportedConversation:
    title: str | None = None
    cues: list[_Cue] = []
    for line in text.splitlines():
        found = _line_cue(line)
        if found is not None:
            cues.append(found[0])
            continue
        stripped = line.strip()
        if not stripped:
            continue
        if not cues:
            h1 = _H1.match(stripped)
            if h1 and title is None:
                title = h1["title"].removeprefix("Transcript: ")
            continue  # preamble before the first cue
        cues[-1].text.append(stripped)
    turns = merge(cues)
    if not turns:
        raise unreadable("No timed lines were found in that transcript.")
    return ImportedConversation(turns, title, None, "timestamped-text")


# -- MM3 companion transcript ------------------------------------------------------------------


def is_companion(text: str) -> bool:
    return text.lstrip("\ufeff").startswith("---") and "<!-- mm3:transcript-data v" in text


def parse_companion(text: str, filename: str) -> ImportedConversation:
    """The companion's hidden data block, used exactly: one turn per segment, with its times
    and word timings."""
    from meetingmaster3.errors import MM3Error
    from meetingmaster3.markdown.transcript_format import parse_transcript

    try:
        parsed = parse_transcript(text)
    except MM3Error as exc:
        raise unreadable(f"That MeetingMaster3 transcript cannot be read: {exc.message}") from exc
    named = parsed.doc.named()
    timed = named.timed
    turns = [
        ImportedTurn(
            speaker=(s.speaker_name or "") if s.speaker_label else "",
            role="other" if s.speaker_label else None,
            text=s.text,
            start=s.start if timed else None,
            end=s.end if timed else None,
            words=tuple(s.words) if timed else (),
        )
        for s in named.segments
        if s.text.strip()
    ]
    if not turns:
        raise unreadable("That MeetingMaster3 transcript has no speech in it.")
    return ImportedConversation(turns, parsed.doc.title, None, "mm3-companion")


# -- WebVTT and SubRip -------------------------------------------------------------------------


def _blocks(text: str) -> list[list[str]]:
    return [
        [ln.rstrip() for ln in b.splitlines()] for b in re.split(r"\n[ \t]*\n", text) if b.strip()
    ]


def _caption_cue(lines: list[str], *, vtt: bool) -> _Cue | None:
    found = next(((i, m) for i, ln in enumerate(lines) if (m := _CUE_TIME.match(ln))), None)
    if found is None:
        return None
    at, m = found
    speaker = ""
    body: list[str] = []
    for raw in lines[at + 1 :]:
        line = raw.strip()
        if vtt:
            voice = _VOICE.search(line)
            if voice and not speaker:
                speaker = _clean_name(voice["name"])
            line = _TAG.sub("", line).strip()
        else:
            line = re.sub(r"</?(?:i|b|u|font)[^>]{0,100}>", "", line).strip()
        if not line:
            continue
        prefix = _PREFIX_NAME.match(line)
        if prefix and not speaker and not body:
            speaker, line = _clean_name(prefix["name"]), prefix["text"]
        body.append(line)
    return _Cue(speaker, _clock(m["a"]), _clock(m["b"]), body)


def is_vtt(text: str) -> bool:
    return text.lstrip("\ufeff").startswith("WEBVTT")


def srt_score(text: str) -> float:
    blocks = _blocks(text)
    hits = sum(
        1 for b in blocks if len(b) >= 2 and b[0].strip().isdigit() and _CUE_TIME.match(b[1])
    )
    return hits / len(blocks) if blocks and hits >= 1 else 0.0


def parse_vtt(text: str, filename: str) -> ImportedConversation:
    cues = []
    for block in _blocks(text)[1:]:  # the first block is the WEBVTT header
        if block[0].startswith(("NOTE", "STYLE", "REGION")):
            continue
        cue = _caption_cue(block, vtt=True)
        if cue is not None:
            cues.append(cue)
    turns = merge(cues)
    if not turns:
        raise unreadable("No captions were found in that WebVTT file.")
    return ImportedConversation(turns, None, None, "webvtt")


def parse_srt(text: str, filename: str) -> ImportedConversation:
    cues = [c for b in _blocks(text) if (c := _caption_cue(b, vtt=False)) is not None]
    turns = merge(cues)
    if not turns:
        raise unreadable("No subtitles were found in that SRT file.")
    return ImportedConversation(turns, None, None, "srt")
