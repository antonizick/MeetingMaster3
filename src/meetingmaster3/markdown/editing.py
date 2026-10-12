"""Split a note into editable parts and join edited parts back without disturbing other bytes.

The review workspace (Phase 11) edits a note as a fixed sequence of parts: the frontmatter
block, the user text before, between and after sections, and the content *between* each valid
section's marker lines. The marker lines themselves are never sent to the browser as editable
text, so an edit cannot delete or alter them (R11). Joining puts the original marker lines back.

Browsers hand textarea contents back with LF line endings. A part that is unchanged apart from
that is restored byte-for-byte; a changed part takes the document's own line ending.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from meetingmaster3.domain.note import LOOSE_MARKER_RE, split_lines
from meetingmaster3.errors import MM3Error
from meetingmaster3.markdown.frontmatter import FrontmatterError, split_frontmatter
from meetingmaster3.markdown.note_parser import BOM
from meetingmaster3.markdown.sections import detect_newline, parse_inner, scan_sections

E_EDIT_STRUCTURE = "E_EDIT_STRUCTURE"
E_MARKER_EDIT = "E_MARKER_EDIT"


@dataclass(frozen=True)
class EditableSection:
    id: str
    title: str
    open_line: str
    """The opening marker line exactly as in the file (with its line ending)."""
    inner: str
    """Everything between the two marker lines: the heading, a blank line, the body."""
    close_line: str


@dataclass(frozen=True)
class EditableDocument:
    bom: str
    frontmatter: str
    """The frontmatter block with its fences, exactly as in the file ('' when there is none)."""
    texts: tuple[str, ...]
    """User text around sections: ``len(sections) + 1`` entries."""
    sections: tuple[EditableSection, ...]
    newline: str

    def join(self) -> str:
        parts = [self.bom, self.frontmatter, self.texts[0]]
        for section, text in zip(self.sections, self.texts[1:], strict=True):
            parts += [section.open_line, section.inner, section.close_line, text]
        return "".join(parts)

    @property
    def section_ids(self) -> list[str]:
        return [s.id for s in self.sections]

    def section(self, section_id: str) -> EditableSection | None:
        return next((s for s in self.sections if s.id == section_id), None)


def split_document(text: str) -> EditableDocument:
    """Split ``text`` so that ``split_document(text).join() == text``."""
    bom = BOM if text.startswith(BOM) else ""
    rest = text[len(bom) :]
    try:
        fm, body = split_frontmatter(rest)
    except FrontmatterError:
        fm, body = None, rest
    head = fm.raw if fm is not None else ""
    if head + body != rest:  # pragma: no cover - split_frontmatter cuts at the closing fence
        head, body = "", rest
    scan = scan_sections(body)
    texts: list[str] = []
    sections: list[EditableSection] = []
    pos = 0
    for span in scan.sections:
        texts.append(body[pos : span.open.start])
        inner = body[span.inner_start : span.inner_end]
        title, _ = parse_inner(inner)
        sections.append(
            EditableSection(
                id=span.id,
                title=title or span.id,
                open_line=body[span.open.start : span.open.end],
                inner=inner,
                close_line=body[span.close.start : span.close.end],
            )
        )
        pos = span.close.end
    texts.append(body[pos:])
    return EditableDocument(bom, head, tuple(texts), tuple(sections), detect_newline(text))


def _lf(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def restore(original: str, submitted: str, newline: str) -> str:
    """``original`` if ``submitted`` is the same text with LF endings, else ``submitted`` with
    the document's line ending."""
    submitted = _lf(submitted)
    if submitted == _lf(original):
        return original
    return submitted.replace("\n", newline) if newline == "\r\n" else submitted


def marker_lines(text: str) -> list[str]:
    """Lines that look like MM3 section markers, whitespace-trimmed."""
    return [ln.strip() for ln in split_lines(_lf(text)) if LOOSE_MARKER_RE.match(ln)]


@dataclass(frozen=True)
class Edits:
    """What the browser sends back: every part, as plain text with LF line endings."""

    texts: Sequence[str]
    sections: Mapping[str, str]
    frontmatter: str | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> Edits:
        texts = data.get("texts")
        sections = data.get("sections")
        frontmatter = data.get("frontmatter")
        if (
            not isinstance(texts, list)
            or not all(isinstance(t, str) for t in texts)
            or not isinstance(sections, dict)
            or not all(isinstance(k, str) and isinstance(v, str) for k, v in sections.items())
            or not (frontmatter is None or isinstance(frontmatter, str))
        ):
            raise MM3Error(
                "E_BODY_INVALID",
                "The editor sent an incomplete note.",
                "Reload the page and try again.",
                status_code=422,
            )
        return cls(texts=list(texts), sections=dict(sections), frontmatter=frontmatter)


def _structure_error() -> MM3Error:
    return MM3Error(
        E_EDIT_STRUCTURE,
        "The editor's copy of the note no longer matches the note it was opened from.",
        "Reload the page. Your unsaved draft is kept and can be restored.",
        status_code=409,
    )


def marker_changes(doc: EditableDocument, edits: Edits) -> list[str]:
    """Descriptions of edits that add, remove or alter marker-like lines."""
    changes: list[str] = []
    for i, (old, new) in enumerate(zip(doc.texts, edits.texts, strict=True)):
        if marker_lines(old) != marker_lines(new):
            where = "before the first section" if i == 0 else f"after section {i}"
            changes.append(f"text {where}")
    if edits.frontmatter is not None and marker_lines(edits.frontmatter):
        changes.append("properties")
    return changes


def apply_edits(doc: EditableDocument, edits: Edits, *, allow_marker_changes: bool = False) -> str:
    """The document with ``edits`` applied. Marker lines of valid sections are always the
    originals. Raises ``E_EDIT_STRUCTURE`` if the parts do not match ``doc``, and
    ``E_MARKER_EDIT`` if an edit adds a marker inside a section, or changes marker-like lines in
    user text without ``allow_marker_changes``."""
    if len(edits.texts) != len(doc.texts) or set(edits.sections) - set(doc.section_ids):
        raise _structure_error()
    for section in doc.sections:
        if LOOSE_MARKER_RE.search(_lf(edits.sections.get(section.id, ""))):
            raise MM3Error(
                E_MARKER_EDIT,
                f"The '{section.title}' section now contains an MM3 section marker line.",
                "Remove the '<!-- mm3:section… -->' line from the section and save again.",
                status_code=422,
            )
    changes = marker_changes(doc, edits)
    if changes and not allow_marker_changes:
        raise MM3Error(
            E_MARKER_EDIT,
            "This edit adds, removes or changes an MM3 section marker line ("
            + ", ".join(changes)
            + ").",
            "Damaged markers stop sections from being regenerated. Undo the change, or confirm "
            "that you want to save it anyway.",
            status_code=409,
            details={"confirm": True, "where": changes},
        )
    nl = doc.newline
    texts = [restore(o, n, nl) for o, n in zip(doc.texts, edits.texts, strict=True)]
    sections = []
    for section in doc.sections:
        inner = section.inner
        if section.id in edits.sections:
            inner = restore(section.inner, edits.sections[section.id], nl)
            if inner and not inner.endswith("\n"):
                inner += nl  # the close marker must start its own line
        sections.append((section, inner))
    frontmatter = doc.frontmatter
    if edits.frontmatter is not None:
        frontmatter = restore(doc.frontmatter, edits.frontmatter, nl)
        if frontmatter and not frontmatter.endswith("\n"):
            frontmatter += nl

    out = [doc.bom, frontmatter]
    for i, (section, inner) in enumerate(sections):
        text = texts[i]
        if text and not text.endswith("\n"):
            text += nl  # the open marker must start its own line
        close = section.close_line
        if texts[i + 1] and not close.endswith("\n"):
            close += nl
        out += [text, section.open_line, inner, close]
    out.append(texts[-1])
    return "".join(out)


def edits_of(doc: EditableDocument) -> Edits:
    """The parts of ``doc`` as the browser would send them back unchanged."""
    return Edits(
        texts=[_lf(t) for t in doc.texts],
        sections={s.id: _lf(s.inner) for s in doc.sections},
        frontmatter=_lf(doc.frontmatter),
    )
