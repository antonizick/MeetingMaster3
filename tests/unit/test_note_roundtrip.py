"""Round-trip properties for notes (the Phase 03 acceptance criteria)."""

from __future__ import annotations

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from meetingmaster3.domain.note import Note, Section, split_lines
from meetingmaster3.errors import MM3Error
from meetingmaster3.markdown.note_parser import ParsedNote, parse_note
from meetingmaster3.markdown.note_writer import render_note
from meetingmaster3.markdown.sections import append_section, replace_section, scan_sections

from .strategies import notes, sections, user_text

ROUNDTRIP = settings(max_examples=500, deadline=None, suppress_health_check=[HealthCheck.too_slow])

_JUNK_LINES = st.one_of(
    user_text.map(lambda t: t.replace("\n", " ").replace("\r", " ") + "\n"),
    st.sampled_from(
        [
            "\n",
            "   \n",
            "# Another H1\n",
            "## Notes I added\n",
            "- **Participants:** Someone\n",
            "---\n",
            "<!-- mm3:section:summary -->\n",
            "<!-- /mm3:section:summary -->\n",
            "<!-- mm3:section:Bad Id -->\n",
            "<!--mm3:section:x-->\n",
            "<!-- MM3:SECTION:y -->\n",
            "  <!-- mm3:section:spaced -->  \n",
            "<!-- /mm3:section:spaced -->\t\n",
            "<!-- mm3:section:extra --> trailing\n",
        ]
    ),
)


def _parse_or_reject(text: str) -> ParsedNote:
    try:
        return parse_note(text)
    except MM3Error:
        assume(False)
        raise  # pragma: no cover


def _is_insertion(old: str, new: str) -> bool:
    """``new == old[:p] + inserted + old[p:]`` for some ``p``."""
    prefix = 0
    while prefix < len(old) and old[prefix] == new[prefix]:
        prefix += 1
    return len(new) >= len(old) and new.endswith(old[prefix:])


@st.composite
def edited_texts(draw: st.DrawFn) -> str:
    """A rendered note, then edited the way a user might: lines inserted or deleted outside
    the frontmatter (including stray or broken markers), trailing whitespace, frontmatter
    comments, and optionally the whole file converted to CRLF."""
    text = render_note(draw(notes()))
    lines = split_lines(text)
    fm_end = next(i for i, ln in enumerate(lines[1:], start=1) if ln.rstrip("\r\n") == "---")
    for _ in range(draw(st.integers(0, 6))):
        op = draw(st.sampled_from(["insert", "insert", "delete", "trailing", "fm_comment"]))
        body_idx = draw(st.integers(fm_end + 1, max(fm_end + 1, len(lines))))
        if op == "insert":
            lines.insert(body_idx, draw(_JUNK_LINES))
        elif op == "delete" and body_idx < len(lines):
            del lines[body_idx]
        elif op == "trailing" and body_idx < len(lines) and lines[body_idx].endswith("\n"):
            lines[body_idx] = lines[body_idx][:-1] + draw(st.sampled_from([" ", "\t", "  "])) + "\n"
        elif op == "fm_comment":
            idx = draw(st.integers(1, fm_end))
            lines.insert(idx, draw(st.sampled_from(["# a comment\n", "\n", "#\n"])))
            fm_end += 1
    out = "".join(lines)
    if draw(st.booleans()):
        out = out.replace("\r\n", "\n").replace("\n", "\r\n")
    return out


@ROUNDTRIP
@given(notes())
def test_parse_of_render_is_identity(note: Note) -> None:
    parsed = parse_note(render_note(note))
    assert parsed.ok
    assert parsed.note == note


@ROUNDTRIP
@given(notes())
def test_rendering_is_stable(note: Note) -> None:
    text = render_note(note)
    parsed = parse_note(text)
    assert render_note(parsed.note) == text
    assert render_note(parsed.note, base=parsed) == text


@ROUNDTRIP
@given(edited_texts())
def test_unchanged_user_edited_file_renders_byte_identical(text: str) -> None:
    parsed = _parse_or_reject(text)
    assert render_note(parsed.note, base=parsed) == text


@ROUNDTRIP
@given(edited_texts(), user_text, st.data())
def test_replace_section_preserves_everything_outside_markers(
    text: str, new_body: str, data: st.DataObject
) -> None:
    scan = scan_sections(text)
    assume(scan.sections)
    span = data.draw(st.sampled_from(scan.sections))
    out = replace_section(text, span.id, new_body)
    prefix, suffix = text[: span.inner_start], text[span.inner_end :]
    assert out.startswith(prefix)
    assert out.endswith(suffix)
    after = scan_sections(out)
    assert [s.id for s in after.sections] == [s.id for s in scan.sections]
    assert [e.kind for e in after.errors] == [e.kind for e in scan.errors]


@ROUNDTRIP
@given(edited_texts(), st.data())
def test_model_level_section_change_keeps_other_bytes(text: str, data: st.DataObject) -> None:
    parsed = _parse_or_reject(text)
    assume(parsed.note.sections)
    target = data.draw(st.sampled_from(parsed.note.sections))
    new = data.draw(sections(target.id))
    out = render_note(parsed.note.with_section(new), base=parsed)
    reparsed = parse_note(out)
    assert reparsed.note.section(target.id) == new
    for other in parsed.note.sections:
        if other.id != target.id:
            assert parsed.raw_sections[other.id][1] in out
    assert reparsed.note.preamble == parsed.note.preamble
    assert reparsed.note.interstitial_text == parsed.note.interstitial_text
    assert reparsed.note.trailing_text == parsed.note.trailing_text


@ROUNDTRIP
@given(edited_texts(), sections())
def test_append_section_is_a_pure_insertion(text: str, section: Section) -> None:
    out, sid = append_section(text, section)
    assert sid in [s.id for s in scan_sections(out).sections]
    assert _is_insertion(text, out)


@ROUNDTRIP
@given(edited_texts())
def test_meta_change_keeps_unknown_property_bytes(text: str) -> None:
    parsed = _parse_or_reject(text)
    chunks = parsed.frontmatter.chunks or {}
    extras = [chunks[k] for k in parsed.note.extra_properties if k in chunks]
    changed = parsed.note.meta.model_copy(update={"title": parsed.note.meta.title + " v2"})
    out = render_note(parsed.note.with_meta(changed), base=parsed)
    reparsed = parse_note(out)
    assert reparsed.note.meta == changed
    assert reparsed.note.extra_properties == parsed.note.extra_properties
    assert reparsed.note.blocks == parsed.note.blocks
    for chunk in extras:
        assert chunk.rstrip("\r\n") in out
    body = text[len(parsed.frontmatter.raw) :]
    assert out.endswith(body)
