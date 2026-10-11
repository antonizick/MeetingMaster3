"""Section markers: a strict scanner plus byte-preserving section operations (R11).

Grammar (one marker per line, optional surrounding spaces or tabs)::

    <!-- mm3:section:<id> -->
    ...section content...
    <!-- /mm3:section:<id> -->

A section is *valid* when its id has exactly one open and one close marker, the close marker is
the next marker line after the open one, and no error mentions the id. Operations on a valid
section rewrite only the bytes between its two marker lines; everything else is untouched.
Invalid sections are reported as :class:`MarkerError` and never guessed at.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Literal

from meetingmaster3.domain.note import (
    AI_RECOMMENDATIONS_ID,
    HEADING_RE,
    LOOSE_MARKER_RE,
    MARKER_RE,
    SECTION_ID_RE,
    Section,
    close_marker,
    normalise_body,
    open_marker,
    split_lines,
)
from meetingmaster3.errors import MM3Error

MarkerErrorKind = Literal[
    "malformed",  # looks like a marker but does not follow the grammar
    "invalid_id",  # well-formed marker with an id outside [a-z0-9][a-z0-9-]*
    "duplicate",  # the same id is opened (or closed) more than once
    "unclosed",  # opened but never closed
    "unexpected_close",  # closed without being opened
    "mismatched",  # closes an id that is not open while another section is open
    "misnested",  # opened inside another section, or closed out of order
    "invalid_content",  # markers are fine but the content cannot be represented as a section
]


@dataclass(frozen=True)
class MarkerError:
    kind: MarkerErrorKind
    line: int
    """1-based line number of the offending marker."""
    message: str
    section_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class MarkerLine:
    line: int
    start: int
    """Offset of the first character of the line."""
    end: int
    """Offset just past the line's newline (or end of text)."""
    section_id: str | None
    """``None`` for malformed or invalid-id lines."""
    is_close: bool


@dataclass(frozen=True)
class SectionSpan:
    id: str
    open: MarkerLine
    close: MarkerLine

    @property
    def inner_start(self) -> int:
        return self.open.end

    @property
    def inner_end(self) -> int:
        return self.close.start


@dataclass(frozen=True)
class SectionScan:
    sections: tuple[SectionSpan, ...]
    errors: tuple[MarkerError, ...]
    markers: tuple[MarkerLine, ...] = field(repr=False)

    @property
    def ok(self) -> bool:
        return not self.errors

    def get(self, section_id: str) -> SectionSpan | None:
        return next((s for s in self.sections if s.id == section_id), None)

    def errors_for(self, section_id: str) -> list[MarkerError]:
        return [e for e in self.errors if section_id in e.section_ids]

    @property
    def mentioned_ids(self) -> set[str]:
        return {m.section_id for m in self.markers if m.section_id} | {
            i for e in self.errors for i in e.section_ids
        }


class SectionMarkerError(MM3Error):
    """A section operation was refused because its markers are missing or damaged (R11)."""

    def __init__(self, section_id: str, errors: list[MarkerError]):
        detail = "; ".join(f"line {e.line}: {e.message}" for e in errors) or "no markers found"
        super().__init__(
            "section_markers_invalid",
            f"Section '{section_id}' cannot be regenerated: {detail}.",
            "Append a fresh copy of the section at the end of the note, or cancel. "
            "Content outside the markers is never modified.",
            status_code=409,
        )
        self.section_id = section_id
        self.errors = errors


def detect_newline(text: str) -> Literal["\n", "\r\n"]:
    """The document's line ending, judged by its first line break (LF if none)."""
    i = text.find("\n")
    return "\r\n" if i > 0 and text[i - 1] == "\r" else "\n"


def scan_sections(doc: str) -> SectionScan:
    """Find every marker line and classify sections as valid or broken."""
    markers: list[MarkerLine] = []
    errors: list[MarkerError] = []
    offset = 0
    for lineno, raw in enumerate(split_lines(doc), start=1):
        content = raw[:-1] if raw.endswith("\n") else raw
        start, offset = offset, offset + len(raw)
        if not LOOSE_MARKER_RE.match(content):
            continue
        m = MARKER_RE.match(content)
        if m is None:
            errors.append(MarkerError("malformed", lineno, "malformed section marker"))
            markers.append(MarkerLine(lineno, start, offset, None, False))
            continue
        sid, is_close = m["id"], bool(m["close"])
        if not SECTION_ID_RE.match(sid):
            errors.append(MarkerError("invalid_id", lineno, f"invalid section id {sid!r}"))
            markers.append(MarkerLine(lineno, start, offset, None, is_close))
            continue
        markers.append(MarkerLine(lineno, start, offset, sid, is_close))

    named = [m for m in markers if m.section_id is not None]
    seen_open: Counter[str | None] = Counter()
    seen_close: Counter[str | None] = Counter()
    stack: list[str] = []
    for mk in named:
        sid = mk.section_id
        if sid is None:  # pragma: no cover - `named` only holds lines with an id
            continue
        if not mk.is_close:
            seen_open[sid] += 1
            if seen_open[sid] > 1:
                errors.append(MarkerError("duplicate", mk.line, f"'{sid}' opened again", (sid,)))
            if stack:  # charged to the outer section; the inner one may still be intact
                errors.append(
                    MarkerError(
                        "misnested",
                        mk.line,
                        f"'{sid}' opened before '{stack[-1]}' was closed",
                        (stack[-1],),
                    )
                )
            stack.append(sid)
            continue
        seen_close[sid] += 1
        if seen_close[sid] > 1:
            errors.append(MarkerError("duplicate", mk.line, f"'{sid}' closed again", (sid,)))
        if stack and stack[-1] == sid:
            stack.pop()
        elif sid in stack:
            inner = stack[-1]
            errors.append(
                MarkerError(
                    "misnested", mk.line, f"'{sid}' closed while '{inner}' is open", (sid, inner)
                )
            )
            stack.remove(sid)
        elif stack:
            errors.append(
                MarkerError(
                    "mismatched",
                    mk.line,
                    f"'{sid}' closed but '{stack[-1]}' is the open section",
                    (sid, stack[-1]),
                )
            )
        elif seen_close[sid] == 1:
            errors.append(
                MarkerError("unexpected_close", mk.line, f"'{sid}' closed but never opened", (sid,))
            )
    for sid in stack:
        line = next(mk.line for mk in reversed(named) if mk.section_id == sid and not mk.is_close)
        errors.append(MarkerError("unclosed", line, f"'{sid}' is never closed", (sid,)))

    broken = {i for e in errors for i in e.section_ids}
    sections = [
        SectionSpan(a.section_id, a, b)
        for a, b in pairwise(markers)
        if a.section_id is not None
        and not a.is_close
        and b.is_close
        and b.section_id == a.section_id
        and a.section_id not in broken
    ]
    valid = {s.id for s in sections}
    for mk in named:  # e.g. the inner id of interleaved sections: A, B, /A, /B
        sid = mk.section_id
        if sid is not None and sid not in valid and sid not in broken:
            errors.append(
                MarkerError("misnested", mk.line, f"'{sid}' overlaps another section", (sid,))
            )
            broken.add(sid)
    errors.sort(key=lambda e: e.line)
    return SectionScan(tuple(sections), tuple(errors), tuple(markers))


def list_sections(doc: str) -> list[str]:
    """Ids of the valid sections, in document order."""
    return [s.id for s in scan_sections(doc).sections]


def _require(doc: str, section_id: str) -> SectionSpan:
    scan = scan_sections(doc)
    span = scan.get(section_id)
    if span is None:
        raise SectionMarkerError(section_id, scan.errors_for(section_id))
    return span


def _check_content(text: str) -> None:
    if LOOSE_MARKER_RE.search(text):
        raise MM3Error(
            "section_content_has_markers",
            "Generated content contains an mm3 section marker.",
            "Remove the marker comment from the content and try again.",
        )


def render_inner(title: str, body: str, newline: str = "\n") -> str:
    """Canonical section content: ``## Title``, a blank line, the body, a final newline."""
    body = normalise_body(body)
    heading = f"## {title}{newline}" if title else ""
    if not body:
        return heading
    return heading + (newline if heading else "") + body.replace("\n", newline) + newline


def parse_inner(inner: str) -> tuple[str, str]:
    """Split section content into ``(title, body)``. The title comes from a leading heading."""
    lines = inner.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    while lines and not lines[0].strip(" \t"):
        lines.pop(0)
    if lines and (m := HEADING_RE.match(lines[0])):
        return " ".join((m["title"] or "").split()), normalise_body("\n".join(lines[1:]))
    return "", normalise_body("\n".join(lines))


def render_section(section: Section, newline: str = "\n") -> str:
    """A complete section, marker lines included, ending with a newline."""
    return (
        open_marker(section.id)
        + newline
        + render_inner(section.title, section.body_markdown, newline)
        + close_marker(section.id)
        + newline
    )


def section_inner(doc: str, section_id: str) -> str:
    """The raw content between a valid section's markers."""
    span = _require(doc, section_id)
    return doc[span.inner_start : span.inner_end]


def replace_section_inner(doc: str, section_id: str, inner: str) -> str:
    """Replace everything between the section's markers with ``inner`` (used as given, plus a
    final newline if missing)."""
    span = _require(doc, section_id)
    _check_content(inner)
    if inner and not inner.endswith("\n"):
        inner += detect_newline(doc)
    return doc[: span.inner_start] + inner + doc[span.inner_end :]


def replace_section(doc: str, section_id: str, new_body: str, *, title: str | None = None) -> str:
    """Replace a section's body. The existing heading line is kept byte-for-byte unless a new
    ``title`` is given. Raises :class:`SectionMarkerError` if the section is not valid."""
    span = _require(doc, section_id)
    newline = detect_newline(doc)
    _check_content(new_body)
    body = normalise_body(new_body)
    lines = split_lines(doc[span.inner_start : span.inner_end])
    while lines and not lines[0].strip(" \t\r\n"):
        lines.pop(0)
    if title is not None:
        heading = f"## {' '.join(title.split())}{newline}" if title.strip() else ""
    elif lines and HEADING_RE.match(lines[0].rstrip("\n")):
        heading = lines[0] if lines[0].endswith("\n") else lines[0] + newline
    else:
        heading = ""
    inner = heading
    if body:
        inner += (newline if heading else "") + body.replace("\n", newline) + newline
    return doc[: span.inner_start] + inner + doc[span.inner_end :]


def fresh_section_id(doc: str, wanted: str) -> str:
    """``wanted``, or ``wanted-2``, ``wanted-3``... if any marker already mentions it."""
    used = scan_sections(doc).mentioned_ids
    if wanted not in used:
        return wanted
    n = 2
    while True:
        suffix = f"-{n}"
        candidate = wanted[: 64 - len(suffix)] + suffix
        if candidate not in used:
            return candidate
        n += 1


def append_section(doc: str, section: Section) -> tuple[str, str]:
    """Add ``section`` as a new marked section and return ``(new_doc, section_id)``.

    It goes at the end of the document, or immediately before a valid AI Recommendations
    section so that one stays last. If the id is already mentioned by any marker (for example a
    damaged copy of the same section), a fresh id with a numeric suffix is used. Existing bytes
    are never changed: this is a pure insertion.
    """
    newline = detect_newline(doc)
    sid = fresh_section_id(doc, section.id)
    block = render_section(section.model_copy(update={"id": sid}), newline)
    ai = scan_sections(doc).get(AI_RECOMMENDATIONS_ID)
    if ai is not None and sid != AI_RECOMMENDATIONS_ID:
        pos = ai.open.start
        return doc[:pos] + block + newline + doc[pos:], sid
    prefix = ""
    if doc:
        prefix = ("" if doc.endswith("\n") else newline) + newline
    return doc + prefix + block, sid


__all__ = [
    "MarkerError",
    "MarkerLine",
    "SectionMarkerError",
    "SectionScan",
    "SectionSpan",
    "append_section",
    "detect_newline",
    "fresh_section_id",
    "list_sections",
    "parse_inner",
    "render_inner",
    "render_section",
    "replace_section",
    "replace_section_inner",
    "scan_sections",
    "section_inner",
]
