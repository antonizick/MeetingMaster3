from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
import yaml
from hypothesis import given, settings

from meetingmaster3.markdown.frontmatter import (
    FrontmatterError,
    emit_key,
    parse_wikilink,
    render_frontmatter,
    same,
    scalar,
    split_frontmatter,
)

from .strategies import extra_keys, yaml_values

USER_FM = """---
# my comment at the top
title: Product Sync
aliases:
  - PS   # inline comment
  - Sync
date: 2026-10-11T14:00:00
custom: {a: 1}
mm3-id: 00000000-0000-0000-0000-000000000001
---
body
"""


def test_split_and_chunks() -> None:
    fm, body = split_frontmatter(USER_FM)
    assert fm is not None and body == "body\n"
    assert list(fm.data) == ["title", "aliases", "date", "custom", "mm3-id"]
    assert fm.prefix == "# my comment at the top\n"
    assert fm.chunks is not None
    assert fm.chunks["aliases"] == "aliases:\n  - PS   # inline comment\n  - Sync\n"
    assert fm.data["date"] == dt.datetime(2026, 10, 11, 14, 0)


def test_unchanged_is_verbatim_and_changed_key_only_is_reemitted() -> None:
    fm, _ = split_frontmatter(USER_FM)
    assert fm is not None
    assert render_frontmatter(dict(fm.data), base=fm) == fm.raw
    out = render_frontmatter({**fm.data, "title": "Renamed"}, base=fm)
    assert out == fm.raw.replace("title: Product Sync", "title: Renamed")
    added = render_frontmatter({**fm.data, "new-key": [1, "two"]}, base=fm)
    assert added.endswith("mm3-id: 00000000-0000-0000-0000-000000000001\nnew-key: [1, two]\n---\n")
    removed = render_frontmatter({k: v for k, v in fm.data.items() if k != "custom"}, base=fm)
    assert "custom" not in removed and "# inline comment" in removed


@pytest.mark.parametrize(
    "text",
    [
        "no frontmatter\n",
        "---\nnot closed\n",
        " ---\na: 1\n---\n",
    ],
)
def test_no_frontmatter(text: str) -> None:
    assert split_frontmatter(text) == (None, text)


@pytest.mark.parametrize(
    "text",
    ["---\na: [1\n---\n", "---\n- just\n- a list\n---\n", "---\n1: x\n---\n"],
)
def test_invalid_frontmatter(text: str) -> None:
    with pytest.raises(FrontmatterError):
        split_frontmatter(text)


def test_empty_and_unsplittable_frontmatter() -> None:
    fm, body = split_frontmatter("---\n---\nx")
    assert fm is not None and fm.data == {} and body == "x"
    assert render_frontmatter({"a": 1}, base=fm) == "---\na: 1\n---\n"
    fm2, _ = split_frontmatter("---\n{a: 1, b: 2}\n---\n")
    assert fm2 is not None and fm2.chunks is None
    assert render_frontmatter({"a": 1, "b": 3}, base=fm2) == "---\na: 1\nb: 3\n---\n"
    fm3, _ = split_frontmatter("---\na: &x 1\nb: *x\n---\n")  # alias across keys
    assert fm3 is not None and fm3.chunks is None
    fm4, _ = split_frontmatter("---\na: 1\n---")  # closing fence at EOF
    assert fm4 is not None
    assert render_frontmatter({"a": 2}, base=fm4) == "---\na: 2\n---\n"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Product Sync", "Product Sync"),
        ("[[Note]]", '"[[Note]]"'),
        ("yes", '"yes"'),
        ("true", '"true"'),
        ("0o17", '"0o17"'),
        ("1.0", '"1.0"'),
        ("a: b", '"a: b"'),
        ("a #b", '"a #b"'),
        (" padded", '" padded"'),
        ("", '""'),
        ("line\u2028sep", '"line\\u2028sep"'),
        ("qwen3:8b", "qwen3:8b"),
        (True, "true"),
        (3, "3"),
        (1e-05, "1.0e-05"),
        (None, ""),
        (dt.date(2026, 10, 11), "2026-10-11"),
    ],
)
def test_scalar_style(value: Any, expected: str) -> None:
    assert scalar(value) == expected


def test_flow_lists_and_mappings() -> None:
    assert emit_key("tags", ["a", "b c", "x,y", "[z]"]) == 'tags: [a, b c, "x,y", "[z]"]\n'
    assert emit_key("tags", []) == "tags: []\n"
    assert emit_key("m", {}) == "m: {}\n"
    assert emit_key("mm3-speakers", {"SPEAKER_00": "Alice", "00": "Bob"}) == (
        'mm3-speakers:\n  SPEAKER_00: Alice\n  "00": Bob\n'
    )
    assert emit_key("nested", {"a": [1, 2]}) == "nested:\n  a:\n  - 1\n  - 2\n"
    assert emit_key("k", None, "\r\n") == "k:\r\n"


@settings(max_examples=500, deadline=None)
@given(extra_keys, yaml_values)
def test_emit_key_round_trips_any_yaml_value(key: str, value: Any) -> None:
    text = emit_key(key, value)
    loaded = yaml.safe_load(text)
    assert list(loaded) == [key]
    assert same(loaded[key], value)


def test_same_is_strict() -> None:
    assert not same(True, 1)
    assert not same({"a": 1, "b": 2}, {"b": 2, "a": 1})
    assert same([1, {"a": "x"}], [1, {"a": "x"}])
    assert not same([1], [1, 2])


def test_parse_wikilink() -> None:
    assert parse_wikilink("[[Note|Alias]]") == "Note"
    assert parse_wikilink(" [[Note]] ") == "Note"
    assert parse_wikilink("Note") == "Note"
    assert parse_wikilink("") is None
    assert parse_wikilink(3) is None
    assert parse_wikilink("[[]]") is None
