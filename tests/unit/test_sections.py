"""Section markers: every R11 failure mode, and byte-preserving operations."""

from __future__ import annotations

import pytest

from meetingmaster3.domain.note import Section
from meetingmaster3.errors import MM3Error
from meetingmaster3.markdown.sections import (
    SectionMarkerError,
    append_section,
    detect_newline,
    fresh_section_id,
    list_sections,
    parse_inner,
    render_inner,
    replace_section,
    replace_section_inner,
    scan_sections,
    section_inner,
)

DOC = """# Title
User intro.

<!-- mm3:section:summary -->
## Summary

Old summary.
<!-- /mm3:section:summary -->

My own notes between sections.

<!-- mm3:section:ai-recommendations -->
## AI Recommendations

- Old rec
<!-- /mm3:section:ai-recommendations -->
Trailing user text"""


def kinds(doc: str) -> list[tuple[str, int, tuple[str, ...]]]:
    return [(e.kind, e.line, e.section_ids) for e in scan_sections(doc).errors]


def test_valid_document() -> None:
    scan = scan_sections(DOC)
    assert scan.ok
    assert list_sections(DOC) == ["summary", "ai-recommendations"]
    assert section_inner(DOC, "summary") == "## Summary\n\nOld summary.\n"


@pytest.mark.parametrize(
    ("doc", "expected"),
    [
        (  # missing close
            "<!-- mm3:section:a -->\nx\n",
            [("unclosed", 1, ("a",))],
        ),
        (  # missing open
            "x\n<!-- /mm3:section:a -->\n",
            [("unexpected_close", 2, ("a",))],
        ),
        (  # duplicate section
            "<!-- mm3:section:a -->\n<!-- /mm3:section:a -->\n"
            "<!-- mm3:section:a -->\n<!-- /mm3:section:a -->\n",
            [("duplicate", 3, ("a",)), ("duplicate", 4, ("a",))],
        ),
        (  # mis-nested (interleaved)
            "<!-- mm3:section:a -->\n<!-- mm3:section:b -->\n"
            "<!-- /mm3:section:a -->\n<!-- /mm3:section:b -->\n",
            [("misnested", 2, ("a",)), ("misnested", 3, ("a", "b"))],
        ),
        (  # mismatched close
            "<!-- mm3:section:a -->\n<!-- /mm3:section:b -->\n",
            [("unclosed", 1, ("a",)), ("mismatched", 2, ("b", "a"))],
        ),
        (  # malformed marker
            "<!-- mm3:section:a --> trailing\n",
            [("malformed", 1, ())],
        ),
        (  # invalid id
            "<!-- mm3:section:Summary -->\n<!-- /mm3:section:Summary -->\n",
            [("invalid_id", 1, ()), ("invalid_id", 2, ())],
        ),
    ],
)
def test_marker_failure_modes(doc: str, expected: list[tuple[str, int, tuple[str, ...]]]) -> None:
    assert sorted(kinds(doc)) == sorted(expected)
    assert list_sections(doc) == []


def test_nested_inner_section_stays_usable_but_outer_is_refused() -> None:
    doc = (
        "<!-- mm3:section:outer -->\n<!-- mm3:section:inner -->\nx\n"
        "<!-- /mm3:section:inner -->\n<!-- /mm3:section:outer -->\n"
    )
    assert list_sections(doc) == ["inner"]
    assert [e.kind for e in scan_sections(doc).errors_for("outer")] == ["misnested"]
    with pytest.raises(SectionMarkerError):
        replace_section(doc, "outer", "y")


def test_unclosed_section_does_not_poison_later_sections() -> None:
    doc = "<!-- mm3:section:a -->\nbroken\n\n<!-- mm3:section:b -->\nok\n<!-- /mm3:section:b -->\n"
    assert list_sections(doc) == ["b"]
    assert [e.kind for e in scan_sections(doc).errors] == ["unclosed", "misnested"]


def test_marker_whitespace_and_crlf_tolerated() -> None:
    doc = "  <!--   mm3:section:a   -->  \r\nbody\r\n\t<!-- /mm3:section:a -->\r\n"
    assert list_sections(doc) == ["a"]
    assert detect_newline(doc) == "\r\n"
    assert detect_newline("no newline") == "\n"


def test_replace_section_byte_preservation() -> None:
    out = replace_section(DOC, "summary", "New summary.\n\n- point")
    prefix, suffix = DOC.split("## Summary\n")[0], DOC.split("Old summary.\n")[1]
    assert out.startswith(prefix + "## Summary\n\nNew summary.\n\n- point\n<!-- /mm3:section")
    assert out.endswith(suffix)
    assert out.count("My own notes between sections.") == 1


def test_replace_section_keeps_user_heading_and_crlf() -> None:
    doc = "<!-- mm3:section:a -->\r\n### My Heading  \r\nold\r\n<!-- /mm3:section:a -->\r\n"
    out = replace_section(doc, "a", "new\nlines")
    assert out == (
        "<!-- mm3:section:a -->\r\n### My Heading  \r\n\r\nnew\r\nlines\r\n"
        "<!-- /mm3:section:a -->\r\n"
    )
    assert "## Renamed\r\n" in replace_section(doc, "a", "x", title="Renamed")
    assert (
        replace_section(doc, "a", "", title="")
        == "<!-- mm3:section:a -->\r\n<!-- /mm3:section:a -->\r\n"
    )
    headingless = "<!-- mm3:section:a -->\nold\n<!-- /mm3:section:a -->\n"
    assert (
        replace_section(headingless, "a", "new")
        == "<!-- mm3:section:a -->\nnew\n<!-- /mm3:section:a -->\n"
    )


def test_refusals() -> None:
    with pytest.raises(SectionMarkerError) as exc:
        replace_section("<!-- mm3:section:a -->\n", "a", "x")
    assert exc.value.code == "section_markers_invalid"
    assert "never closed" in exc.value.message and "Append" in exc.value.hint
    with pytest.raises(SectionMarkerError) as missing:
        replace_section(DOC, "nope", "x")
    assert "no markers found" in missing.value.message
    with pytest.raises(MM3Error) as bad:
        replace_section(DOC, "summary", "<!-- /mm3:section:summary -->")
    assert bad.value.code == "section_content_has_markers"


def test_replace_section_inner() -> None:
    out = replace_section_inner(DOC, "summary", "raw")
    assert "<!-- mm3:section:summary -->\nraw\n<!-- /mm3:section:summary -->" in out
    assert replace_section_inner(DOC, "summary", "").count("summary -->\n<!-- /mm3") == 1


def test_append_goes_before_ai_recommendations() -> None:
    out, sid = append_section(DOC, Section(id="decisions", title="Decisions", body_markdown="- d"))
    assert sid == "decisions"
    assert list_sections(out) == ["summary", "decisions", "ai-recommendations"]
    assert (
        out.replace(
            "<!-- mm3:section:decisions -->\n## Decisions\n\n- d\n"
            "<!-- /mm3:section:decisions -->\n\n",
            "",
        )
        == DOC
    )


def test_append_after_damaged_section_uses_fresh_id() -> None:
    doc = "<!-- mm3:section:summary -->\nbroken, never closed\n"
    out, sid = append_section(doc, Section(id="summary", title="Summary", body_markdown="new"))
    assert sid == "summary-2"
    assert out.startswith(doc)
    assert list_sections(out) == ["summary-2"]
    assert fresh_section_id(out, "summary") == "summary-3"
    assert append_section("", Section(id="a", title="A"))[0] == (
        "<!-- mm3:section:a -->\n## A\n<!-- /mm3:section:a -->\n"
    )
    assert append_section("x", Section(id="a", title="A"))[0].startswith("x\n\n<!-- mm3")
    long = "a" * 64
    assert fresh_section_id(f"<!-- mm3:section:{long} -->\n", long) == "a" * 62 + "-2"


def test_inner_render_and_parse() -> None:
    assert render_inner("T", "") == "## T\n"
    assert render_inner("", "b") == "b\n"
    assert render_inner("T", "\n\nb\n\n", "\r\n") == "## T\r\n\r\nb\r\n"
    assert parse_inner("\n## T  \n\nbody\n") == ("T", "body")
    assert parse_inner("##\nbody") == ("", "body")
    assert parse_inner("just text\n") == ("", "just text")
