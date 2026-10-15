"""Backlink scanner and rewriter (Phase 15d, ADR-0040)."""

from __future__ import annotations

from pathlib import Path

import pytest

from meetingmaster3.vault import links
from meetingmaster3.vault.links import build_index, code_spans, rewrite_links, scan_backlinks

OLD = "M/2026/2026-09-22 - Foo.md"
NEW = "M/2025/2025-08-18 - Bar.md"
OLD_R = "M/2026/2026-09-22 - Foo (Transcript).md"
NEW_R = "M/2025/2025-08-18 - Bar (Transcript).md"
OLD_C = "M/2026/2026-09-22 - Foo.transcript.md"
NEW_C = "M/2025/2025-08-18 - Bar.transcript.md"
RENAMES = {OLD: NEW, OLD_R: NEW_R, OLD_C: NEW_C}


def make(root: Path, rel: str, text: str = "x") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")
    return path


@pytest.fixture
def root(tmp_path: Path) -> Path:
    r = (tmp_path / "v").resolve()
    for rel in RENAMES:
        make(r, rel)
    (r / ".obsidian").mkdir()
    return r


def rewrite(root: Path, text: str, source: str = "Daily.md") -> str:
    make(root, source, text)
    scan = scan_backlinks(root, RENAMES)
    hits = [n for n in scan.notes if n.rel == source]
    return hits[0].new_text if hits else text


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("[[2026-09-22 - Foo]]", "[[2025-08-18 - Bar]]"),
        ("[[2026-09-22 - Foo|my alias]]", "[[2025-08-18 - Bar|my alias]]"),
        ("[[2026-09-22 - Foo#Decisions Made]]", "[[2025-08-18 - Bar#Decisions Made]]"),
        ("[[2026-09-22 - Foo#^abc123|x]]", "[[2025-08-18 - Bar#^abc123|x]]"),
        ("![[2026-09-22 - Foo#Summary]]", "![[2025-08-18 - Bar#Summary]]"),
        ("[[M/2026/2026-09-22 - Foo]]", "[[M/2025/2025-08-18 - Bar]]"),
        ("[[2026-09-22 - foo.md]]", "[[2025-08-18 - Bar.md]]"),
        ("| a | [[2026-09-22 - Foo\\|t]] |", "| a | [[2025-08-18 - Bar\\|t]] |"),
        ("[[2026-09-22 - Foo (Transcript)|read]]", "[[2025-08-18 - Bar (Transcript)|read]]"),
        ("[[2026-09-22 - Foo.transcript]]", "[[2025-08-18 - Bar.transcript]]"),
        (
            "[t](M/2026/2026-09-22%20-%20Foo.md#Sum%20x)",
            "[t](M/2025/2025-08-18%20-%20Bar.md#Sum%20x)",
        ),
        ("[t](<M/2026/2026-09-22 - Foo.md>)", "[t](<M/2025/2025-08-18 - Bar.md>)"),
        (
            '[t](M/2026/2026-09-22%20-%20Foo%20(Transcript).md "title")',
            '[t](M/2025/2025-08-18%20-%20Bar%20(Transcript).md "title")',
        ),
        ('related: "[[2026-09-22 - Foo]]"', 'related: "[[2025-08-18 - Bar]]"'),
    ],
)
def test_every_link_form_is_rewritten_keeping_the_rest(root: Path, before: str, after: str) -> None:
    text = f"Before {before} after.\r\n"
    assert rewrite(root, text) == f"Before {after} after.\r\n"


def test_relative_markdown_links_stay_relative(root: Path) -> None:
    text = "[t](2026-09-22%20-%20Foo.md)"
    assert rewrite(root, text, "M/2026/Sibling.md") == "[t](../2025/2025-08-18%20-%20Bar.md)"


def test_links_in_code_are_not_links(root: Path) -> None:
    text = (
        "`[[2026-09-22 - Foo]]` and ``x [[2026-09-22 - Foo]] y``\n"
        "```\n[[2026-09-22 - Foo]]\n```\n"
        "~~~~md\n[[2026-09-22 - Foo]]\n~~~~\n"
        "real [[2026-09-22 - Foo]]\n"
    )
    out = rewrite(root, text)
    assert out.count("[[2026-09-22 - Foo]]") == 4
    assert out.endswith("real [[2025-08-18 - Bar]]\n")
    assert len(code_spans(text)) == 4


def test_unrelated_links_and_urls_are_untouched(root: Path) -> None:
    text = "[[2026-09-22 - Foobar]] [[Other]] [w](https://x.org/2026-09-22%20-%20Foo.md) [[]]"
    make(root, "Other.md")
    assert rewrite(root, text) == text


def test_an_ambiguous_name_is_left_alone_with_a_warning(root: Path) -> None:
    make(root, "Elsewhere/2026-09-22 - Foo.md")
    make(root, "Daily.md", "[[2026-09-22 - Foo]] [[M/2026/2026-09-22 - Foo]]")
    scan = scan_backlinks(root, RENAMES)
    (note,) = scan.notes
    assert note.new_text == "[[2026-09-22 - Foo]] [[M/2025/2025-08-18 - Bar]]"
    assert any("could mean several files" in w for w in scan.warnings)


def test_same_folder_wins_when_names_are_shared(root: Path) -> None:
    make(root, "Elsewhere/2026-09-22 - Foo.md")
    make(root, "M/2026/Sibling.md", "[[2026-09-22 - Foo]]")
    (note,) = scan_backlinks(root, RENAMES).notes
    assert note.new_text == "[[2025-08-18 - Bar]]"


def test_a_new_name_shared_elsewhere_becomes_path_qualified(root: Path) -> None:
    make(root, "Elsewhere/2025-08-18 - Bar.md")
    make(root, "Daily.md", "[[2026-09-22 - Foo|a]]")
    scan = scan_backlinks(root, RENAMES)
    assert scan.notes[0].new_text == "[[M/2025/2025-08-18 - Bar|a]]"
    assert any("also called" in w for w in scan.warnings)


def test_archives_hidden_folders_and_excluded_files_are_skipped(root: Path) -> None:
    link = "[[2026-09-22 - Foo]]"
    make(root, "M/2026/Archive/old.md", f"---\nmm3-archived: 2026-10-01T00:00:00\n---\n{link}")
    make(root, ".trash/Daily.md", link)
    make(root, ".obsidian/x.md", link)
    make(root, "Mine.md", link)
    scan = scan_backlinks(root, RENAMES, exclude=["Mine.md"])
    assert scan.notes == []


def test_the_scan_is_bounded(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(links, "MAX_FILE_BYTES", 10)
    make(root, "Big.md", "[[2026-09-22 - Foo]] " * 5)
    scan = scan_backlinks(root, RENAMES)
    assert scan.notes == [] and any("very large" in w for w in scan.warnings)
    monkeypatch.setattr(links, "MAX_FILES", 1)
    assert build_index(root)[2] is True


def test_symlinked_notes_are_ignored(root: Path, tmp_path: Path) -> None:
    outside = make(tmp_path, "outside.md", "[[2026-09-22 - Foo]]")
    (root / "Link.md").symlink_to(outside)
    assert scan_backlinks(root, RENAMES).notes == []
    assert outside.read_text() == "[[2026-09-22 - Foo]]"


def test_rewrite_edits_carry_line_numbers(root: Path) -> None:
    index = build_index(root)[0]
    after = build_index(root)[0]
    for o, n in RENAMES.items():
        after.remove(o)
        after.add(n)
    text = "a\nb [[2026-09-22 - Foo]]\n"
    out, edits, _ = rewrite_links(text, "Daily.md", RENAMES, index, after)
    assert out == "a\nb [[2025-08-18 - Bar]]\n"
    assert [(e.line, e.old, e.new) for e in edits] == [(2, "2026-09-22 - Foo", "2025-08-18 - Bar")]
