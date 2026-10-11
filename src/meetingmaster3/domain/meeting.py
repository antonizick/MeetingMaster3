"""Meeting metadata: everything MM3 stores in a note's frontmatter (spec §5, R9)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field, field_validator

from meetingmaster3.domain.transcript import DomainModel, SpeakerMap, clean_name

UNTITLED = "Untitled meeting"


def clean_tag(tag: str) -> str:
    """Obsidian tags carry no ``#`` in frontmatter and cannot contain spaces."""
    return "-".join(tag.strip().lstrip("#").split())


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(i for i in items if i))


class MeetingMeta(DomainModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    title: str = UNTITLED
    date: datetime | None = None
    participants: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    location: str | None = None
    template_id: str | None = None
    backend: str | None = None
    model: str | None = None
    generated_at: datetime | None = None
    audio_ref: str | None = None
    """Wikilink target (without brackets) of the audio copied into the vault, if any (R8)."""
    transcript_ref: str | None = None
    """Wikilink target (without brackets) of the companion transcript."""
    speakers: SpeakerMap = Field(default_factory=SpeakerMap)

    @field_validator("title")
    @classmethod
    def _title(cls, v: str) -> str:
        return clean_name(v) or UNTITLED

    @field_validator("location", "template_id", "backend", "model", "audio_ref", "transcript_ref")
    @classmethod
    def _optional_line(cls, v: str | None) -> str | None:
        return (clean_name(v) or None) if v is not None else None

    @field_validator("audio_ref", "transcript_ref")
    @classmethod
    def _link_target(cls, v: str | None) -> str | None:
        if v is not None and any(c in v for c in "[]|"):
            raise ValueError("a wikilink target cannot contain '[', ']' or '|'")
        return v

    @field_validator("participants")
    @classmethod
    def _participants(cls, v: list[str]) -> list[str]:
        return _dedupe([clean_name(p) for p in v])

    @field_validator("tags")
    @classmethod
    def _tags(cls, v: list[str]) -> list[str]:
        return _dedupe([clean_tag(t) for t in v])
