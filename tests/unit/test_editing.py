"""Editable parts of a note: split/join identity and byte preservation of edits (Phase 11)."""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from meetingmaster3.errors import MM3Error
from meetingmaster3.markdown.editing import (
    E_EDIT_STRUCTURE,
    E_MARKER_EDIT,
    Edits,
    apply_edits,
    edits_of,
    restore,
    split_document,
)
from meetingmaster3.markdown.sections import scan_sections

FIXTURES = Path(__file__).parents[1] / "fixtures" / "notes"
NOTES = sorted(p for p in FIXTURES.glob("*.md") if not p.name.endswith(".transcript.md"))


def read(path: Path) -> str:
    with open(path, encoding="utf-8", newline="") as fh:
        return fh.read()


def variants() -> list[tuple[str, str]]:
    out = []
    for path in NOTES:
        text = read(path)
        out.append((path.name, text))
        out.append((path.name + " (CRLF)", text.replace("\r\n", "\n").replace("\n", "\r\n")))
        out.append((path.name + " (BOM)", "﻿" + text))
    out.append(
        ("no frontmatter", "# Title\n\n<!-- mm3:section:a -->\n## A\n\nx\n<!-- /mm3:section:a -->")
    )
    out.append(("empty", ""))
    return out


@pytest.mark.parametrize(("name", "text"), variants(), ids=[n for n, _ in variants()])
def test_split_join_and_unchanged_edits_are_identity(name: str, text: str) -> None:
    doc = split_document(text)
    assert doc.join() == text
    assert apply_edits(doc, edits_of(doc)) == text
    assert len(doc.texts) == len(doc.sections) + 1


def test_marker_lines_are_not_part_of_any_editable_text() -> None:
    doc = split_document(read(FIXTURES / "2026-10-11 - Product Sync.md"))
    assert doc.section_ids == ["summary", "decisions", "action-items", "ai-recommendations"]
    for part in (*doc.texts, *(s.inner for s in doc.sections)):
        assert "mm3:section" not in part
    summary = doc.section("summary")
    assert summary is not None and summary.title == "Summary"
    assert summary.open_line == "<!-- mm3:section:summary -->\n"


def test_damaged_sections_stay_in_user_text() -> None:
    doc = split_document(read(FIXTURES / "damaged-markers.md"))
    damaged = {e for err in scan_sections(doc.join()).errors for e in err.section_ids}
    assert damaged and not damaged & set(doc.section_ids)
    assert any("mm3:section" in t for t in doc.texts)


@settings(max_examples=150, deadline=None)
@given(
    which=st.integers(min_value=0, max_value=3),
    body=st.text(
        st.characters(blacklist_categories=("Cs",), blacklist_characters="\r"), max_size=200
    ),
    crlf=st.booleans(),
)
def test_editing_one_section_keeps_every_other_byte(which: int, body: str, crlf: bool) -> None:
    text = read(FIXTURES / "2026-10-11 - Product Sync.md")
    if crlf:
        text = text.replace("\n", "\r\n")
    doc = split_document(text)
    sid = doc.section_ids[which]
    if "mm3" in body and "section" in body:
        return  # marker-like content is refused (tested below)
    edits = edits_of(doc)
    new = apply_edits(doc, Edits(edits.texts, {**edits.sections, sid: body}, edits.frontmatter))
    old_span, new_span = scan_sections(text).get(sid), scan_sections(new).get(sid)
    assert old_span and new_span
    assert new[: new_span.inner_start] == text[: old_span.inner_start]
    assert new[new_span.inner_end :] == text[old_span.inner_end :]
    assert scan_sections(new).ok


def test_changed_part_takes_the_documents_line_ending() -> None:
    text = read(FIXTURES / "2026-10-11 - Product Sync.md").replace("\n", "\r\n")
    doc = split_document(text)
    edits = edits_of(doc)
    texts = list(edits.texts)
    texts[1] = texts[1] + "My note\nline two\n"
    new = apply_edits(doc, Edits(texts, edits.sections, edits.frontmatter))
    assert "My note\r\nline two\r\n" in new
    assert "\n" not in new.replace("\r\n", "")


def test_missing_trailing_newlines_are_added_so_markers_start_lines() -> None:
    doc = split_document("intro\n<!-- mm3:section:a -->\n## A\n\nx\n<!-- /mm3:section:a -->")
    new = apply_edits(doc, Edits(["intro without newline", "after"], {"a": "## A\n\ny"}))
    assert new == (
        "intro without newline\n<!-- mm3:section:a -->\n## A\n\ny\n<!-- /mm3:section:a -->\nafter"
    )
    assert scan_sections(new).ok


def test_marker_in_a_section_is_refused() -> None:
    doc = split_document(read(FIXTURES / "2026-10-11 - Product Sync.md"))
    edits = edits_of(doc)
    bad = {**edits.sections, "summary": "## Summary\n\n<!-- /mm3:section:summary -->\n"}
    with pytest.raises(MM3Error) as exc:
        apply_edits(doc, Edits(edits.texts, bad), allow_marker_changes=True)
    assert exc.value.code == E_MARKER_EDIT and exc.value.status_code == 422


def test_marker_change_in_user_text_needs_confirmation() -> None:
    doc = split_document(read(FIXTURES / "damaged-markers.md"))
    edits = edits_of(doc)
    texts = [t.replace("<!-- mm3:section", "<!-- removed", 1) for t in edits.texts]
    assert texts != list(edits.texts)
    with pytest.raises(MM3Error) as exc:
        apply_edits(doc, Edits(texts, edits.sections))
    assert exc.value.code == E_MARKER_EDIT and exc.value.details["confirm"] is True
    assert "<!-- removed" in apply_edits(
        doc, Edits(texts, edits.sections), allow_marker_changes=True
    )


def test_structure_mismatch_is_refused() -> None:
    doc = split_document(read(FIXTURES / "2026-10-11 - Product Sync.md"))
    edits = edits_of(doc)
    for bad in (Edits(edits.texts[:-1], edits.sections), Edits(edits.texts, {"nope": "x"})):
        with pytest.raises(MM3Error) as exc:
            apply_edits(doc, bad)
        assert exc.value.code == E_EDIT_STRUCTURE and exc.value.status_code == 409


def test_restore_and_payload_validation() -> None:
    assert restore("a\r\nb\r\n", "a\nb\n", "\r\n") == "a\r\nb\r\n"
    assert restore("a\r\nb\r\n", "a\nc\n", "\r\n") == "a\r\nc\r\n"
    assert restore("a\nb", "a\r\nb", "\n") == "a\nb"
    with pytest.raises(MM3Error):
        Edits.from_dict({"texts": "nope", "sections": {}})
    with pytest.raises(MM3Error):
        Edits.from_dict({"texts": [], "sections": {"a": 1}})
    ok = Edits.from_dict({"texts": ["x"], "sections": {"a": "b"}, "frontmatter": None})
    assert ok.texts == ["x"] and ok.frontmatter is None
