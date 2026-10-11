"""Transcript, segment, word and speaker-map models (pure, no I/O)."""

from __future__ import annotations

import re
import uuid
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SPEAKER_LABEL_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class DomainModel(BaseModel):
    """Base for every domain model: immutable, strict about unknown fields, finite floats."""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class Word(DomainModel):
    """One word. WhisperX leaves ``start``/``end`` empty for words it could not align."""

    start: float | None = None
    end: float | None = None
    text: str
    score: float | None = None


class Segment(DomainModel):
    id: int = Field(ge=0)
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    speaker_label: str | None = None
    """Diarization label such as ``SPEAKER_00``; ``None`` when not diarized."""
    speaker_name: str | None = None
    """Resolved display name; only set on the copy returned by :meth:`SpeakerMap.apply`."""
    text: str
    words: list[Word] = Field(default_factory=list)

    @field_validator("speaker_label")
    @classmethod
    def _label(cls, v: str | None) -> str | None:
        if v is not None and not SPEAKER_LABEL_RE.match(v):
            raise ValueError(f"invalid speaker label {v!r}")
        return v


class Transcript(DomainModel):
    segments: list[Segment] = Field(default_factory=list)
    language: str | None = None
    duration: float | None = Field(default=None, ge=0)
    model: str | None = None
    diarized: bool = False

    @model_validator(mode="after")
    def _unique_ids(self) -> Self:
        ids = [s.id for s in self.segments]
        if len(ids) != len(set(ids)):
            raise ValueError("segment ids must be unique")
        return self

    @property
    def speaker_labels(self) -> list[str]:
        """Distinct labels in natural order (``SPEAKER_2`` before ``SPEAKER_10``)."""
        return sorted({s.speaker_label for s in self.segments if s.speaker_label}, key=natural_key)


def natural_key(text: str) -> tuple[tuple[int, int | str], ...]:
    return tuple((0, int(p)) if p.isdigit() else (1, p) for p in re.split(r"(\d+)", text) if p)


def clean_name(name: str) -> str:
    """Collapse whitespace (including newlines) so a name fits on one Markdown line."""
    return " ".join(name.split())


class SpeakerMap(DomainModel):
    """Maps diarization labels to confirmed display names. Unmapped labels stay unmapped here;
    :meth:`display_name` gives them a stable placeholder ("Speaker 1", "Speaker 2", ...)."""

    names: dict[str, str] = Field(default_factory=dict)

    @field_validator("names")
    @classmethod
    def _names(cls, v: dict[str, str]) -> dict[str, str]:
        out: dict[str, str] = {}
        for label, name in v.items():
            if not SPEAKER_LABEL_RE.match(label):
                raise ValueError(f"invalid speaker label {label!r}")
            cleaned = clean_name(name)
            if not cleaned:
                raise ValueError(f"empty name for {label}")
            out[label] = cleaned
        return out

    def display_name(self, label: str | None, labels: list[str]) -> str:
        """Name for ``label``. Placeholders number labels by their natural order in ``labels``,
        so renaming one speaker never renumbers the others."""
        if label is None:
            return "Speaker"
        if label in self.names:
            return self.names[label]
        ordered = sorted(set(labels) | {label}, key=natural_key)
        return f"Speaker {ordered.index(label) + 1}"

    def with_name(self, label: str, name: str) -> SpeakerMap:
        return SpeakerMap(names={**self.names, label: name})

    def apply(self, transcript: Transcript) -> Transcript:
        """A copy of ``transcript`` with every segment's ``speaker_name`` resolved."""
        labels = transcript.speaker_labels
        segments = [
            s.model_copy(update={"speaker_name": self.display_name(s.speaker_label, labels)})
            for s in transcript.segments
        ]
        return transcript.model_copy(update={"segments": segments})


class Turn(DomainModel):
    """Consecutive segments by the same speaker, shown as one block in the companion file."""

    speaker_label: str | None
    segments: list[Segment]

    @property
    def start(self) -> float:
        return self.segments[0].start

    @property
    def end(self) -> float:
        return self.segments[-1].end

    @property
    def text(self) -> str:
        return " ".join(t for s in self.segments if (t := " ".join(s.text.split())))


def group_turns(transcript: Transcript) -> list[Turn]:
    """Merge consecutive same-speaker segments into turns."""
    turns: list[list[Segment]] = []
    for seg in transcript.segments:
        if turns and turns[-1][-1].speaker_label == seg.speaker_label:
            turns[-1].append(seg)
        else:
            turns.append([seg])
    return [Turn(speaker_label=t[0].speaker_label, segments=t) for t in turns]


TRANSCRIPT_KEYS = (
    "mm3-version",
    "mm3-id",
    "mm3-note",
    "mm3-speakers",
    "duration",
    "language",
    "mm3-transcription-model",
    "mm3-diarized",
)
"""Frontmatter keys MM3 owns in a companion transcript (R9), in the order it writes them."""


class CompanionTranscript(DomainModel):
    """The companion ``.transcript.md`` file: a transcript plus its link to the note."""

    meeting_id: uuid.UUID
    title: str
    note_ref: str | None = None
    """Wikilink target (without brackets) of the main note."""
    transcript: Transcript
    speakers: SpeakerMap = Field(default_factory=SpeakerMap)
    extra_properties: dict[str, Any] = Field(default_factory=dict)
    format_version: int = 1
    newline: Literal["\n", "\r\n"] = "\n"

    @field_validator("title")
    @classmethod
    def _title(cls, v: str) -> str:
        return clean_name(v) or "Untitled meeting"

    @field_validator("extra_properties")
    @classmethod
    def _extras(cls, v: dict[str, Any]) -> dict[str, Any]:
        clash = set(v) & set(TRANSCRIPT_KEYS)
        if clash:
            raise ValueError(f"extra properties clash with MM3 keys: {sorted(clash)}")
        return v

    def named(self) -> Transcript:
        """The transcript with speaker names resolved."""
        return self.speakers.apply(self.transcript)
