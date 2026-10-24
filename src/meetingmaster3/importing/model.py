"""The parser interface: what every import parser returns (pure, no I/O).

A parser turns the bytes of one text file into an :class:`ImportedConversation`: an ordered list
of :class:`ImportedTurn` (who said it, in which role, the text, the time if the file has one, and
how sure the parser is about the speaker). :mod:`meetingmaster3.importing.convert` turns that
into the same :class:`~meetingmaster3.domain.transcript.Transcript` the audio pipeline produces.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from meetingmaster3.domain.transcript import Word
from meetingmaster3.errors import MM3Error

Role = Literal["user", "assistant", "other"]

E_IMPORT_UNREADABLE = "E_IMPORT_UNREADABLE"
E_IMPORT_TOO_LARGE = "E_IMPORT_TOO_LARGE"
E_IMPORT_EMPTY = "E_IMPORT_EMPTY"

MAX_TURNS = 20_000
"""More turns than any real conversation; a file beyond it is rejected rather than parsed."""


@dataclass(frozen=True)
class ImportedTurn:
    speaker: str
    """The name as the file gives it ("Alice", "Grok"), or a role word ("User") when that is all
    the file says. Empty when the file names nobody (an SRT without ``Name:`` prefixes)."""
    role: Role | None
    """``user`` / ``assistant`` for AI conversations, ``other`` for a named person in a
    transcript, ``None`` when unknown."""
    text: str
    """The turn's text. Markdown inside an AI answer (lists, code fences) is kept."""
    start: float | None = None
    """Seconds from the start, or ``None`` for an untimed file (no time is ever invented)."""
    end: float | None = None
    confidence: float = 1.0
    """0-1: how sure the parser is about ``speaker``/``role`` (1.0 when the file says so)."""
    words: tuple[Word, ...] = ()
    """Word timings, when the source has them (an MM3 companion)."""


@dataclass(frozen=True)
class ImportedConversation:
    turns: list[ImportedTurn]
    title: str | None
    started_at: dt.datetime | None
    source_format: str
    """The id of the parser that read the file (see :data:`PARSER_IDS`)."""
    warnings: list[str] = field(default_factory=list)

    @property
    def timed(self) -> bool:
        return bool(self.turns) and all(t.start is not None for t in self.turns)


Parser = Callable[[str, str], ImportedConversation]
"""``(text, filename) -> conversation``. Raises only :class:`MM3Error`."""

FORMAT_NAMES = {
    "mm3-companion": "MeetingMaster3 transcript",
    "timestamped-text": "timestamped transcript",
    "webvtt": "WebVTT captions",
    "srt": "SubRip captions",
    "chat-markdown": "AI conversation (labelled)",
    "chat-unlabelled": "AI conversation (unlabelled)",
    "grok-share": "Grok share link",
}
"""Parser id → name shown in the UI ("Imported from <name>")."""

PARSER_IDS = tuple(FORMAT_NAMES)


def format_name(source_format: str | None) -> str:
    return FORMAT_NAMES.get(source_format or "", source_format or "a text file")


def unreadable(message: str, hint: str = "") -> MM3Error:
    return MM3Error(
        E_IMPORT_UNREADABLE,
        message,
        hint
        or "Import a text file: an AI conversation exported as Markdown, or a transcript "
        "(.txt with [hh:mm:ss] Name: lines, a MeetingMaster3 .transcript.md, .vtt or .srt).",
        status_code=422,
    )


def too_large(limit_mb: int) -> MM3Error:
    return MM3Error(
        E_IMPORT_TOO_LARGE,
        f"That file is larger than the {limit_mb} MB import limit.",
        "Split the conversation, or raise importing.max_mb in the settings.",
        status_code=413,
    )


def empty() -> MM3Error:
    return MM3Error(
        E_IMPORT_EMPTY,
        "No conversation or transcript text was found in that file.",
        "Check that it is the exported conversation or transcript, not an empty file.",
        status_code=422,
    )
