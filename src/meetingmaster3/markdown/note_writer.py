"""Build and render MM3 notes.

``render_note(note)`` writes a fresh, canonical note. ``render_note(note, base=parsed)``
re-renders a note that was read from disk and reuses the original bytes of everything that did
not change: unchanged frontmatter keys (with their comments), user text outside sections, and
unchanged sections. ``render_note(parse_note(text).note, base=parse_note(text)) == text``.
"""

from __future__ import annotations

from typing import Any

from meetingmaster3.domain.meeting import MeetingMeta
from meetingmaster3.domain.note import (
    AI_RECOMMENDATIONS_ID,
    FORMAT_VERSION,
    NOTE_KEYS,
    Block,
    Note,
    Section,
    TextBlock,
)
from meetingmaster3.markdown.frontmatter import render_frontmatter, same, wikilink
from meetingmaster3.markdown.note_parser import BOM, ParsedNote
from meetingmaster3.markdown.sections import render_section

_ALWAYS = frozenset({"title", "participants", "tags", "mm3-version", "mm3-id"})
_DEFAULTS = MeetingMeta()


def semantic(key: str, note: Note | None) -> Any:
    """The domain value behind a frontmatter key (``note=None`` gives the value MM3 assumes
    when the key is missing)."""
    if key == "mm3-version":
        return note.format_version if note else FORMAT_VERSION
    meta = note.meta if note else _DEFAULTS
    attr = {
        "mm3-id": "id",
        "mm3-template": "template_id",
        "mm3-transcript": "transcript_ref",
        "mm3-speakers": "speakers",
        "mm3-generated": "generated_at",
        "mm3-backend": "backend",
        "mm3-model": "model",
        "mm3-audio": "audio_ref",
    }.get(key, key)
    return getattr(meta, attr)


def yaml_value(key: str, note: Note) -> Any:
    """The value MM3 writes for ``key``; ``None`` means "omit the key"."""
    v = semantic(key, note)
    if key == "mm3-id":
        return str(v)
    if key in ("mm3-transcript", "mm3-audio"):
        return wikilink(v) if v else None
    if key == "mm3-speakers":
        return dict(v.names) or None
    if key in ("participants", "tags"):
        return list(v)
    return v


def frontmatter_data(note: Note, base: ParsedNote | None = None) -> dict[str, Any]:
    """The ordered property mapping for ``note``, keeping ``base``'s raw values where the
    domain value did not change."""
    if base is None:
        data = {k: v for k in NOTE_KEYS if (v := yaml_value(k, note)) is not None or k in _ALWAYS}
        data.update(note.extra_properties)
        return data

    items: list[tuple[str, Any]] = []
    for key, raw in base.frontmatter.data.items():
        if key in NOTE_KEYS:
            if semantic(key, base.note) == semantic(key, note):
                items.append((key, raw))
            elif (v := yaml_value(key, note)) is not None:
                items.append((key, v))
        elif key in note.extra_properties:
            v = note.extra_properties[key]
            items.append((key, raw if same(v, raw) else v))
    for key in NOTE_KEYS:
        if key in base.frontmatter.data or semantic(key, note) == semantic(key, None):
            continue
        if (v := yaml_value(key, note)) is None:
            continue
        rank = NOTE_KEYS.index(key)
        after = [
            i for i, (k, _) in enumerate(items) if k in NOTE_KEYS and NOTE_KEYS.index(k) < rank
        ]
        items.insert(after[-1] + 1 if after else 0, (key, v))
    present = {k for k, _ in items}
    items.extend((k, v) for k, v in note.extra_properties.items() if k not in present)
    return dict(items)


def render_header(meta: MeetingMeta, newline: str = "\n") -> str:
    """The Appendix B header block (R10), rendered from metadata."""
    lines = []
    if meta.date is not None:
        lines.append(f"- **Date & Time:** {meta.date:%Y-%m-%d %H:%M}")
    lines.append(f"- **Participants:** {', '.join(meta.participants) or 'Not recorded'}")
    if meta.tags:
        lines.append(f"- **Tags:** {' '.join('#' + t for t in meta.tags)}")
    if meta.location:
        lines.append(f"- **Location / Context:** {meta.location}")
    return "".join(line + newline for line in lines)


def build_note(
    meta: MeetingMeta,
    sections: list[Section],
    *,
    extra_properties: dict[str, Any] | None = None,
    newline: str = "\n",
) -> Note:
    """A new note: H1 title, Appendix B header, then the sections, with AI Recommendations
    moved last (spec Appendix A)."""
    ordered = [s for s in sections if s.id != AI_RECOMMENDATIONS_ID] + [
        s for s in sections if s.id == AI_RECOMMENDATIONS_ID
    ]
    blocks: list[Block] = [
        TextBlock(text=f"# {meta.title}{newline}" + render_header(meta, newline))
    ]
    for section in ordered:
        blocks.append(TextBlock(text=newline))
        blocks.append(section)
    return Note(
        meta=meta,
        extra_properties=extra_properties or {},
        blocks=blocks,
        newline="\r\n" if newline == "\r\n" else "\n",
    )


def render_note(note: Note, base: ParsedNote | None = None) -> str:
    """Render ``note`` to Markdown. See the module docstring for the role of ``base``."""
    fm = render_frontmatter(
        frontmatter_data(note, base),
        newline=note.newline,
        base=base.frontmatter if base else None,
    )
    parts: list[str] = []
    for block in note.blocks:
        if isinstance(block, TextBlock):
            parts.append(block.text)
            continue
        original = base.raw_sections.get(block.id) if base else None
        if original is not None and original[0] == block:
            parts.append(original[1])
        else:
            parts.append(render_section(block, note.newline))
    return (BOM if base and base.bom else "") + fm + "".join(parts)
