"""Hostile-input fuzzing of everything that parses vault files or renders untrusted text
(Phase 15, threat model T-VAULT / T-RENDER / T-PATH).

Vault files are untrusted: a synced or shared vault, or a file another tool wrote, may contain
anything. Parsers must either succeed or raise a user-facing ``MM3Error``, quickly; never hang,
crash with another exception, or let markup through to the browser.
"""

from __future__ import annotations

import contextlib
import re
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from meetingmaster3.errors import MM3Error
from meetingmaster3.markdown.editing import split_document
from meetingmaster3.markdown.frontmatter import split_frontmatter
from meetingmaster3.markdown.note_parser import parse_note
from meetingmaster3.markdown.sections import scan_sections
from meetingmaster3.markdown.transcript_format import parse_transcript
from meetingmaster3.templates.schema import parse_template
from meetingmaster3.vault.naming import sanitize_title
from meetingmaster3.vault.paths import confine
from meetingmaster3.web.render import render_markdown

FUZZ = settings(max_examples=300, deadline=2000, suppress_health_check=[HealthCheck.too_slow])

MM3_ID = "0b5e6d1e-7c1a-4c55-9a59-5d6a3c1b2a10"

#: Fragments that exercise the parsers' special cases, mixed with arbitrary text.
PIECES = [
    "---\n", "---\r\n", f"mm3-id: {MM3_ID}\n", "mm3-id: not-a-uuid\n", "title: x\n",
    "participants: [a, b]\n", "mm3-speakers: {SPEAKER_00: Ann}\n", "date: 2026-13-45\n",
    "tags: !!python/object/apply:os.system ['id']\n", "a: &x [1, 2]\n", "b: *x\n",
    "key: |\n  multi\n", "? complex\n: key\n", "{flow: map}\n", "[1, 2]\n", "\t\x00\x1b",
    "<!-- mm3:section:summary -->\n", "<!-- /mm3:section:summary -->\n",
    "<!-- mm3:section:summary -->", "<!-- mm3:section:Bad Id -->\n",
    "<!-- mm3:transcript-data v1\n", '{"id":0,"start":1,"end":2,"text":"x"}\n', "-->\n",
    "<!-- mm3:prompt:_system -->\n", "<!-- mm3:prompt:summary -->\n", "mm3-template: 1\n",
    "sections:\n  - id: summary\n    title: S\n", "## Heading\n", "**[00:01] Ann:** hi\n",
    "<script>alert(1)</script>", "<img src=x onerror=alert(1)>", "[x](javascript:alert(1))",
    "[y](JaVaScRiPt:alert(1))", "[z](data:text/html,<b>)", "<a href='//evil'>a</a>",
    "‮​", "\r\n", "\n", " ", "9" * 400,
]  # fmt: skip

hostile = st.lists(st.one_of(st.sampled_from(PIECES), st.text(max_size=40)), max_size=40).map(
    "".join
)


def _only_user_errors(fn: Callable[[str], object], text: str) -> None:
    with contextlib.suppress(MM3Error):
        fn(text)


@FUZZ
@given(hostile)
def test_note_parsers_only_raise_user_errors(text: str) -> None:
    for fn in (split_frontmatter, parse_note, parse_transcript, scan_sections, split_document):
        _only_user_errors(fn, text)


@FUZZ
@given(hostile)
def test_template_parser_reports_instead_of_raising(text: str) -> None:
    report = parse_template(text, source="fuzz.md")
    assert report.template is not None or report.issues


def _alias_bomb(depth: int = 9) -> str:
    lines = ['a0: &a0 ["x","x","x","x","x","x","x","x","x","x"]']
    lines += [f"a{i}: &a{i} [" + ",".join([f"*a{i - 1}"] * 10) + "]" for i in range(1, depth)]
    return "\n".join(lines) + f"\nparticipants: *a{depth - 1}\ntags: *a{depth - 1}\n"


def test_yaml_alias_bomb_in_a_note_is_refused_fast() -> None:
    note = f"---\nmm3-id: {MM3_ID}\n{_alias_bomb()}---\n# T\n"
    start = time.monotonic()
    for fn in (split_frontmatter, parse_note, parse_transcript):
        with pytest.raises(MM3Error, match="too many values"):
            fn(note)
    assert split_document(note).join() == note  # the editor treats it as plain text
    assert time.monotonic() - start < 2


def test_yaml_alias_bomb_in_a_template_is_reported_fast() -> None:
    template = f"---\nmm3-template: 1\nid: t\nname: T\n{_alias_bomb()}---\n"
    start = time.monotonic()
    report = parse_template(template + "<!-- mm3:prompt:_system -->\nx\n")
    assert report.template is None and "too many values" in report.issues[0].message
    assert time.monotonic() - start < 2


def test_python_tags_are_never_constructed() -> None:
    with pytest.raises(MM3Error):
        parse_note(f"---\nmm3-id: {MM3_ID}\nx: !!python/object/apply:os.system ['id']\n---\n")


_ON_ATTR = re.compile(r"<[a-z][^>]*\son\w+\s*=", re.IGNORECASE)
_HREF = re.compile(r'href="([^"]*)"', re.IGNORECASE)


@FUZZ
@given(hostile, st.booleans())
def test_rendered_markdown_never_contains_live_markup(text: str, timestamps: bool) -> None:
    html = str(render_markdown(text, timestamps=timestamps))
    lowered = html.lower()
    assert "<script" not in lowered and "<img" not in lowered and "<iframe" not in lowered
    assert not _ON_ATTR.search(html)
    for href in _HREF.findall(html):
        assert href.startswith(("http://", "https://", "mailto:", "#", "/")), href
        assert not href.startswith("//")


@FUZZ
@given(st.text(max_size=60))
def test_sanitized_titles_are_safe_file_names(title: str) -> None:
    clean = sanitize_title(title)
    assert not set(clean) & set('*"\\/<>:|?#^[]')
    assert not any(ord(c) < 32 for c in clean)
    assert len(clean.encode("utf-8")) <= 150
    assert clean == clean.strip(" .")


path_parts = st.lists(
    st.one_of(
        st.sampled_from(["..", ".", "~", "/", "a", "b", "link", "\x00", "C:", "//", "~root"]),
        st.text(alphabet="ab./~", max_size=6),
    ),
    max_size=8,
).map("/".join)


@settings(max_examples=300, deadline=None)
@given(path_parts)
def test_confined_paths_never_leave_the_vault(
    tmp_path_factory: pytest.TempPathFactory, rel: str
) -> None:
    root = tmp_path_factory.getbasetemp() / "fuzz-vault"
    (root / "a").mkdir(parents=True, exist_ok=True)
    outside = tmp_path_factory.getbasetemp() / "outside"
    outside.mkdir(exist_ok=True)
    link = root / "link"
    if not link.is_symlink():
        link.symlink_to(outside)
    root = root.resolve()
    try:
        path = confine(root, rel)
    except MM3Error:
        return
    assert Path(path).resolve().is_relative_to(root)


@pytest.mark.parametrize("value", ["2026-13-45", "[[[[[[[[[[" * 200, "!!int 'x'"])
def test_unbuildable_values_are_frontmatter_errors(value: str) -> None:
    """Found by the fuzzer: ``date: 2026-13-45`` raised a bare ValueError (HTTP 500)."""
    with pytest.raises(MM3Error):
        parse_note(f"---\nmm3-id: {MM3_ID}\ndate: {value}\n---\n")
