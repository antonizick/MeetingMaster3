"""The note document model: frontmatter metadata plus an ordered sequence of text and sections.

User text outside sections is kept in :class:`TextBlock` nodes exactly as written (including
``\\r\\n`` line endings), so a parsed note re-renders byte-for-byte. Section content is
normalised (LF, no leading or trailing blank lines) because MM3 owns it.
The normative format is ``docs/dev-guide/note-format.md``.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from meetingmaster3.domain.meeting import MeetingMeta
from meetingmaster3.domain.transcript import DomainModel, clean_name

FORMAT_VERSION = 1
AI_RECOMMENDATIONS_ID = "ai-recommendations"

SECTION_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
"""Section ids: lowercase letters, digits and hyphens, starting with a letter or digit, ≤ 64."""

MARKER_RE = re.compile(
    r"^[ \t]*<!--[ \t]*(?P<close>/?)mm3:section:(?P<id>[^\s>]*?)[ \t]*-->[ \t]*\r?$", re.M
)
"""A syntactically valid marker line (the id is checked separately against SECTION_ID_RE)."""

LOOSE_MARKER_RE = re.compile(r"^[ \t]*<!--[ \t]*/?[ \t]*mm3[ \t]*:[ \t]*section", re.I | re.M)
"""Anything that looks like an attempt at a marker; used to report malformed markers."""

HEADING_RE = re.compile(r"^(?P<hashes>#{1,6})(?:[ \t]+(?P<title>.*?))?[ \t]*\r?$")
"""An ATX heading line. MM3 writes section headings at level 2."""

NOTE_KEYS = (
    "title",
    "date",
    "participants",
    "tags",
    "location",
    "mm3-version",
    "mm3-id",
    "mm3-template",
    "mm3-transcript",
    "mm3-speakers",
    "mm3-generated",
    "mm3-backend",
    "mm3-model",
    "mm3-audio",
)
"""Frontmatter keys MM3 owns in a note, in the order it writes them."""

HEADER_LINE_RE = re.compile(
    r"^- \*\*(?:Date & Time|Participants|Tags|Location / Context):\*\*.*\r?$"
)


def split_lines(text: str) -> list[str]:
    """Split on ``\n`` only (unlike ``str.splitlines``), keeping the line endings."""
    return re.findall(r"[^\n]*\n|[^\n]+$", text)


def open_marker(section_id: str) -> str:
    return f"<!-- mm3:section:{section_id} -->"


def close_marker(section_id: str) -> str:
    return f"<!-- /mm3:section:{section_id} -->"


def normalise_body(body: str) -> str:
    """LF line endings, without leading or trailing blank lines."""
    lines = body.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    while lines and not lines[0].strip(" \t"):
        lines.pop(0)
    while lines and not lines[-1].strip(" \t"):
        lines.pop()
    return "\n".join(lines)


class TextBlock(DomainModel):
    """User-owned text outside any section, stored verbatim."""

    kind: Literal["text"] = "text"
    text: str


class Section(DomainModel):
    """A regenerable, marker-delimited section. ``body_markdown`` excludes the heading."""

    kind: Literal["section"] = "section"
    id: str
    title: str
    body_markdown: str = ""

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not SECTION_ID_RE.match(v):
            raise ValueError(f"invalid section id {v!r}: use [a-z0-9][a-z0-9-]*, at most 64")
        return v

    @field_validator("title")
    @classmethod
    def _title(cls, v: str) -> str:
        return clean_name(v)

    @field_validator("body_markdown")
    @classmethod
    def _body(cls, v: str) -> str:
        v = normalise_body(v)
        if LOOSE_MARKER_RE.search(v):
            raise ValueError("section body must not contain mm3 section markers")
        return v

    @model_validator(mode="after")
    def _representable(self) -> Self:
        first = self.body_markdown.split("\n", 1)[0]
        if not self.title and HEADING_RE.match(first):
            raise ValueError("a section without a title cannot start with a heading")
        return self


Block = Annotated[TextBlock | Section, Field(discriminator="kind")]


class Note(DomainModel):
    meta: MeetingMeta
    extra_properties: dict[str, Any] = Field(default_factory=dict)
    """Frontmatter keys MM3 does not own (Obsidian properties the user added)."""
    format_version: int = FORMAT_VERSION
    blocks: list[Block] = Field(default_factory=list)
    newline: Literal["\n", "\r\n"] = "\n"
    """Line ending used for content MM3 writes. Existing user text keeps its own endings."""

    @field_validator("extra_properties")
    @classmethod
    def _extras(cls, v: dict[str, Any]) -> dict[str, Any]:
        clash = set(v) & set(NOTE_KEYS)
        if clash:
            raise ValueError(f"extra properties clash with MM3 keys: {sorted(clash)}")
        return v

    @model_validator(mode="before")
    @classmethod
    def _canonical_blocks(cls, data: Any) -> Any:
        """Merge adjacent text, drop empty text, and end text that precedes a section with a
        newline (markers must start a line)."""
        if not isinstance(data, dict) or "blocks" not in data:
            return data
        newline = data.get("newline", "\n")
        merged: list[Any] = []
        for block in data["blocks"]:
            is_text = isinstance(block, TextBlock) or (
                isinstance(block, dict) and block.get("kind", "text") == "text"
            )
            if is_text:
                text = block.text if isinstance(block, TextBlock) else block["text"]
                if merged and isinstance(merged[-1], str):
                    merged[-1] += text
                elif text:
                    merged.append(text)
            else:
                if merged and isinstance(merged[-1], str) and not merged[-1].endswith("\n"):
                    merged[-1] += newline
                merged.append(block)
        blocks = [TextBlock(text=b) if isinstance(b, str) else b for b in merged if b != ""]
        return {**data, "blocks": blocks}

    @model_validator(mode="after")
    def _unique_sections(self) -> Self:
        ids = [s.id for s in self.sections]
        if len(ids) != len(set(ids)):
            raise ValueError("section ids must be unique")
        return self

    @property
    def sections(self) -> list[Section]:
        return [b for b in self.blocks if isinstance(b, Section)]

    def section(self, section_id: str) -> Section | None:
        return next((s for s in self.sections if s.id == section_id), None)

    def _texts_around_sections(self) -> list[str]:
        """Text before, between and after sections: ``len(sections) + 1`` entries."""
        out = [""]
        for b in self.blocks:
            if isinstance(b, Section):
                out.append("")
            else:
                out[-1] += b.text
        return out

    @property
    def preamble(self) -> str:
        """Text before the first section: the H1, the Appendix B header and any user text."""
        return self._texts_around_sections()[0]

    @property
    def interstitial_text(self) -> list[str]:
        """Text between consecutive sections (one entry per gap, possibly empty)."""
        parts = self._texts_around_sections()
        return parts[1:-1] if self.sections else []

    @property
    def trailing_text(self) -> str:
        """Text after the last section (empty when there are no sections)."""
        return self._texts_around_sections()[-1] if self.sections else ""

    @property
    def header_markdown(self) -> str:
        """The Appendix B header block (raw) if the preamble starts with H1 + header lines."""
        lines = split_lines(self.preamble)
        i = 0
        while i < len(lines) and not lines[i].strip():
            i += 1
        if i >= len(lines) or not re.match(r"^# \S", lines[i]):
            return ""
        i += 1
        start = i
        while i < len(lines) and HEADER_LINE_RE.match(lines[i].rstrip("\n")):
            i += 1
        return "".join(lines[start:i])

    def with_section(self, section: Section) -> Note:
        """Replace the section with the same id (it must exist)."""
        if self.section(section.id) is None:
            raise KeyError(section.id)
        blocks = [
            section if isinstance(b, Section) and b.id == section.id else b for b in self.blocks
        ]
        return Note.model_validate({**self.model_dump(exclude={"blocks"}), "blocks": blocks})

    def with_meta(self, meta: MeetingMeta) -> Note:
        return Note(
            meta=meta,
            extra_properties=self.extra_properties,
            format_version=self.format_version,
            blocks=list(self.blocks),
            newline=self.newline,
        )
