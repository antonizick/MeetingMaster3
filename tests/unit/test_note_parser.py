from __future__ import annotations

import datetime as dt
import uuid

import pytest

from meetingmaster3.domain.meeting import MeetingMeta
from meetingmaster3.domain.note import Section
from meetingmaster3.errors import MM3Error
from meetingmaster3.markdown.note_parser import parse_note
from meetingmaster3.markdown.note_writer import build_note, render_header, render_note

ID = "3f2b8c1e-7d4a-4e9b-a6c2-5b1d0e8f9a71"


def doc(frontmatter: str, body: str = "# T\n") -> str:
    return f"---\n{frontmatter}---\n{body}"


def test_lenient_property_values_are_understood_and_kept() -> None:
    text = doc(
        f"mm3-id: {ID}\n"
        "title: 2026\n"
        "date: 2026-10-11\n"
        "participants: Alice, Bob\n"
        "tags: one two,#three\n"
        "location: [Room 1, Room 2]\n"
        "mm3-generated: '2026-10-11T15:00:00+02:00'\n"
        "mm3-transcript: Plain Target\n"
        "mm3-speakers: {SPEAKER_00: Alice, 'bad label': X, SPEAKER_01: ''}\n"
        "mm3-version: 1\n"
    )
    parsed = parse_note(text)
    meta = parsed.note.meta
    assert meta.title == "2026"
    assert meta.date == dt.datetime(2026, 10, 11)
    assert meta.participants == ["Alice", "Bob"]
    assert meta.tags == ["one", "two", "three"]
    assert meta.location == "Room 1, Room 2"
    assert meta.generated_at == dt.datetime(
        2026, 10, 11, 15, tzinfo=dt.timezone(dt.timedelta(hours=2))
    )
    assert meta.transcript_ref == "Plain Target"
    assert meta.speakers.names == {"SPEAKER_00": "Alice"}
    assert len(parsed.warnings) == 2
    assert render_note(parsed.note, base=parsed) == text  # nothing rewritten


def test_unparseable_values_warn_and_survive() -> None:
    text = doc(
        f"mm3-id: {ID}\ndate: next tuesday\nmm3-version: two\nmm3-speakers: [a]\nmm3-generated: 5\n"
    )
    parsed = parse_note(text)
    assert parsed.note.meta.date is None and parsed.note.format_version == 1
    assert len(parsed.warnings) == 4
    assert render_note(parsed.note, base=parsed) == text
    newer = parse_note(doc(f"mm3-id: {ID}\nmm3-version: 9\n"))
    assert newer.note.format_version == 9 and "newer" in newer.warnings[0]


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("# just markdown\n", "not_an_mm3_note"),
        (doc("title: x\n"), "not_an_mm3_note"),
        (doc("mm3-id: not-a-uuid\n"), "invalid_mm3_id"),
        (doc("mm3-id: [\n"), "frontmatter_invalid"),
    ],
)
def test_not_an_mm3_note(text: str, code: str) -> None:
    with pytest.raises(MM3Error) as exc:
        parse_note(text)
    assert exc.value.code == code


def test_unrepresentable_section_content_is_reported_not_lost() -> None:
    body = "<!-- mm3:section:a -->\n##\n## Real heading\n<!-- /mm3:section:a -->\n"
    parsed = parse_note(doc(f"mm3-id: {ID}\n", body))
    assert [e.kind for e in parsed.marker_errors] == ["invalid_content"]
    assert parsed.note.sections == []
    assert render_note(parsed.note, base=parsed) == doc(f"mm3-id: {ID}\n", body)


def test_meta_edits_insert_keys_in_mm3_order_and_drop_cleared_ones() -> None:
    text = doc(f"aliases: [x]\ntitle: T\nmm3-id: {ID}\nlocation: Zoom  # where\nmine: 1\n")
    parsed = parse_note(text)
    meta = parsed.note.meta.model_copy(update={"location": None, "template_id": "decision-log"})
    out = render_note(parsed.note.with_meta(meta), base=parsed)
    assert out == doc(
        f"aliases: [x]\ntitle: T\nmm3-id: {ID}\nmm3-template: decision-log\nmine: 1\n"
    )
    extras = parsed.note.model_copy(update={"extra_properties": {"aliases": ["y"], "new": True}})
    out2 = render_note(extras, base=parsed)
    assert "aliases: [y]\n" in out2 and "mine" not in out2 and out2.count("new: true") == 1
    first = parse_note(doc(f"mm3-id: {ID}\n"))
    added = render_note(
        first.note.with_meta(first.note.meta.model_copy(update={"title": "New"})), base=first
    )
    assert added.startswith("---\ntitle: New\nmm3-id:")


def test_build_note_and_header() -> None:
    meta = MeetingMeta(id=uuid.UUID(ID), title="T")
    assert render_header(meta) == "- **Participants:** Not recorded\n"
    note = build_note(
        meta,
        [Section(id="ai-recommendations", title="AI"), Section(id="s", title="S")],
        newline="\r\n",
    )
    assert [s.id for s in note.sections] == ["s", "ai-recommendations"]
    text = render_note(note)
    assert "\n" not in text.replace("\r\n", "")
    parsed = parse_note(text)
    assert parsed.note == note and parsed.note.newline == "\r\n"
    bom = parse_note("\ufeff" + text)
    assert bom.bom and render_note(bom.note, base=bom) == "\ufeff" + text
