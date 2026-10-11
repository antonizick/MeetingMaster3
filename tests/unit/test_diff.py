from __future__ import annotations

from meetingmaster3.markdown.diff import DiffRow, diff_stats, side_by_side, unified_diff

OLD = "Summary line.\n- point a\n- point b\nEnd."
NEW = "Summary line.\n- point A\n- point b\n- point c\nEnd."


def test_unified_diff() -> None:
    out = unified_diff(OLD, NEW, old_label="v1", new_label="v2")
    assert out.splitlines()[:2] == ["--- v1", "+++ v2"]
    assert "-- point a" in out and "+- point A" in out and "+- point c" in out
    assert unified_diff(OLD, OLD) == ""
    assert unified_diff("a\r\nb", "a\nb") == ""  # line endings are not a change


def test_side_by_side_rows() -> None:
    rows = side_by_side(OLD, NEW)
    assert rows[0] == DiffRow("equal", 1, "Summary line.", 1, "Summary line.")
    assert DiffRow("replace", 2, "- point a", 2, "- point A") in rows
    assert DiffRow("insert", None, None, 4, "- point c") in rows
    assert rows[-1] == DiffRow("equal", 4, "End.", 5, "End.")
    stats = diff_stats(rows)
    assert (stats.added, stats.removed, stats.changed, stats.unchanged) == (1, 0, 1, False)


def test_side_by_side_delete_and_empty() -> None:
    rows = side_by_side("a\nb\nc", "a")
    assert [r.kind for r in rows] == ["equal", "delete", "delete"]
    assert side_by_side("", "") == []
    assert diff_stats(side_by_side("x", "x")).unchanged
    assert [r.kind for r in side_by_side("", "new")] == ["insert"]
