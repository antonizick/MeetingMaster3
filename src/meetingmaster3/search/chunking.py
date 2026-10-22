"""Turn an MM3 note or companion transcript into search passages (pure; no I/O).

Notes: one or more passages per section (the AI Recommendations section is left out: it is the
model's advice, not what was said), plus the user's own text outside the sections. Each passage
starts with the meeting title, date and section heading, so it makes sense on its own both to
the word index and to the embedding model.

Transcripts: the data block's segments (speaker names resolved through ``mm3-speakers``), packed
into windows of about ``chunk_tokens`` with ``overlap`` tokens repeated between neighbours. Each
window keeps its start and end time and the names of the people speaking in it.

Sizes are counted with the app's usual estimate (about four characters per token).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass

from meetingmaster3.domain.note import AI_RECOMMENDATIONS_ID, Section, TextBlock
from meetingmaster3.llm.budget import CHARS_PER_TOKEN
from meetingmaster3.markdown.note_parser import parse_note
from meetingmaster3.markdown.transcript_format import parse_transcript
from meetingmaster3.search.store import Passage

SKIPPED_SECTIONS = frozenset({AI_RECOMMENDATIONS_ID})
_HEADER_LINE_RE = re.compile(r"^\s*-\s+\*\*[^*\n]{1,60}:\*\*")
_H1_RE = re.compile(r"^#\s")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
OTHER_HEADING = "Other notes"
PLACEHOLDER_RE = re.compile(r"^Speaker(?: \d+)?$")
"""Names MM3 gives unnamed speakers ("Speaker 3"): shown in passages, never listed as people."""


@dataclass(frozen=True)
class Chunked:
    mm3_id: str
    kind: str
    title: str
    date: str | None
    participants: tuple[str, ...]
    speakers: tuple[str, ...]
    passages: tuple[Passage, ...]


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _passage(text: str, **fields: object) -> Passage:
    return Passage(text=text, text_hash=text_hash(text), **fields)  # type: ignore[arg-type]


def _pieces(text: str, budget: int) -> list[str]:
    """Paragraphs and lines, with anything longer than ``budget`` split by sentences, then by
    words."""
    out: list[str] = []
    for para in re.split(r"\n\s*\n", text):
        for line in para.splitlines():
            line = line.strip()
            if not line:
                continue
            if len(line) <= budget:
                out.append(line)
                continue
            for sentence in _SENTENCE_RE.split(line):
                while len(sentence) > budget:
                    cut = sentence.rfind(" ", 0, budget)
                    cut = cut if cut > budget // 2 else budget
                    out.append(sentence[:cut].strip())
                    sentence = sentence[cut:].strip()
                if sentence:
                    out.append(sentence)
    return out


def pack(sizes: list[int], budget: int, overlap: int) -> list[range]:
    """Group consecutive pieces (given by their sizes in characters) into windows of at most
    ``budget`` characters; a single longer piece gets a window of its own. Each window after the
    first starts with the trailing pieces of the one before, up to ``overlap`` characters.
    Returns the index range of each window."""
    windows: list[range] = []
    start, size = 0, 0
    fresh = 0  # pieces in the current window that are not overlap from the previous one
    for i, n in enumerate(sizes):
        if fresh and size + n + 1 > budget:
            windows.append(range(start, i))
            carried, new_start = 0, i
            while new_start > start + 1 and carried + sizes[new_start - 1] <= overlap:
                new_start -= 1
                carried += sizes[new_start] + 1
            start, size, fresh = new_start, carried, 0
        size += n + 1
        fresh += 1
    if fresh:
        windows.append(range(start, len(sizes)))
    return windows


def _windows(pieces: list[str], budget: int, overlap: int) -> list[list[str]]:
    return [[pieces[i] for i in w] for w in pack([len(p) for p in pieces], budget, overlap)]


def _date(value: object) -> str | None:
    text = str(value or "")[:10]
    return text if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text) else None


def _head(title: str, date: str | None, *extra: str) -> str:
    first = f"{title} · {date}" if date else title
    return "\n".join([first, *(e for e in extra if e)])


def _user_text(blocks: Iterable[TextBlock]) -> str:
    """The user's text outside sections, without the H1 and the generated header lines."""
    lines = []
    for block in blocks:
        for line in block.text.splitlines():
            if _H1_RE.match(line) or _HEADER_LINE_RE.match(line):
                continue
            lines.append(line)
    return "\n".join(lines).strip()


def chunk_note(text: str, *, chunk_tokens: int, overlap: int, fallback_title: str = "") -> Chunked:
    """Passages of a live MM3 note. Raises ``NoteParseError`` for a file that is not one."""
    parsed = parse_note(text)
    note = parsed.note
    meta = note.meta
    title = meta.title or fallback_title or "Untitled meeting"
    date = meta.date.date().isoformat() if meta.date else None
    budget, over = chunk_tokens * CHARS_PER_TOKEN, overlap * CHARS_PER_TOKEN
    passages: list[Passage] = []
    for block in note.blocks:
        if not isinstance(block, Section) or block.id in SKIPPED_SECTIONS:
            continue
        head = _head(title, date, f"## {block.title}")
        for window in _windows(_pieces(block.body_markdown, budget), budget, over):
            passages.append(
                _passage(head + "\n" + "\n".join(window), heading=block.title, section_id=block.id)
            )
    other = _user_text(b for b in note.blocks if isinstance(b, TextBlock))
    if other:
        head = _head(title, date, f"## {OTHER_HEADING}")
        for window in _windows(_pieces(other, budget), budget, over):
            passages.append(_passage(head + "\n" + "\n".join(window), heading=OTHER_HEADING))
    return Chunked(
        mm3_id=str(meta.id),
        kind="note",
        title=title,
        date=date,
        participants=tuple(meta.participants),
        speakers=tuple(dict.fromkeys(meta.speakers.names.values())),
        passages=tuple(passages),
    )


@dataclass(frozen=True)
class _Line:
    name: str | None
    text: str
    start: float
    end: float


def _render(lines: list[_Line]) -> str:
    """Consecutive lines of one speaker become one ``Name: text`` turn."""
    turns: list[tuple[str | None, list[str]]] = []
    for line in lines:
        if turns and turns[-1][0] == line.name:
            turns[-1][1].append(line.text)
        else:
            turns.append((line.name, [line.text]))
    return "\n".join((f"{n}: " if n else "") + " ".join(parts) for n, parts in turns)


def chunk_transcript(
    text: str,
    *,
    chunk_tokens: int,
    overlap: int,
    title: str | None = None,
    date: str | None = None,
) -> Chunked:
    """Passages of a companion transcript. ``title`` and ``date`` come from its note when it is
    known (the companion has no date of its own). Raises ``TranscriptParseError``."""
    parsed = parse_transcript(text)
    doc = parsed.doc
    transcript = doc.named()
    diarized = transcript.diarized or bool(transcript.speaker_labels)
    title = title or doc.title
    budget, over = chunk_tokens * CHARS_PER_TOKEN, overlap * CHARS_PER_TOKEN
    lines: list[_Line] = []
    for seg in transcript.segments:
        words = " ".join(seg.text.split())
        if not words:
            continue
        name = seg.speaker_name if diarized else None
        for piece in _pieces(words, budget):
            lines.append(_Line(name, piece, seg.start, seg.end))
    sizes = [len(ln.text) + (len(ln.name) + 2 if ln.name else 0) for ln in lines]
    passages: list[Passage] = []
    for window in pack(sizes, budget, over):
        chosen = lines[window.start : window.stop]
        names = tuple(dict.fromkeys(ln.name for ln in chosen if ln.name))
        head = _head(title, date, "Transcript", f"Speakers: {', '.join(names)}" if names else "")
        passages.append(
            _passage(
                head + "\n" + _render(chosen),
                start_s=chosen[0].start,
                end_s=chosen[-1].end,
                speakers=names,
            )
        )
    all_names = tuple(dict.fromkeys(s.speaker_name for s in transcript.segments if diarized))
    return Chunked(
        mm3_id=str(doc.meeting_id),
        kind="transcript",
        title=title,
        date=date,
        participants=(),
        speakers=tuple(n for n in all_names if n and not PLACEHOLDER_RE.match(n)),
        passages=tuple(passages),
    )
