"""Unified and side-by-side diffs of section bodies (stdlib ``difflib``; used by Phase 11)."""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from itertools import zip_longest
from typing import Literal

ChangeKind = Literal["equal", "replace", "delete", "insert"]


def _lines(text: str) -> list[str]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.split("\n") if text else []


def unified_diff(
    old: str, new: str, *, old_label: str = "before", new_label: str = "after", context: int = 3
) -> str:
    """A unified diff (empty string when the texts are equal)."""
    out = difflib.unified_diff(
        _lines(old), _lines(new), fromfile=old_label, tofile=new_label, n=context, lineterm=""
    )
    return "\n".join(out)


@dataclass(frozen=True)
class DiffRow:
    """One row of a side-by-side diff. Line numbers are 1-based; ``None`` on the empty side."""

    kind: ChangeKind
    left_no: int | None
    left: str | None
    right_no: int | None
    right: str | None


def side_by_side(old: str, new: str) -> list[DiffRow]:
    """Paired rows for a two-column diff. Within a changed block, lines are paired in order;
    leftover lines become ``delete`` or ``insert`` rows."""
    a, b = _lines(old), _lines(new)
    rows: list[DiffRow] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if tag == "equal":
            rows.extend(
                DiffRow("equal", i + 1, a[i], j + 1, b[j])
                for i, j in zip(range(i1, i2), range(j1, j2), strict=True)
            )
            continue
        for i, j in zip_longest(range(i1, i2), range(j1, j2)):
            if i is not None and j is not None:
                rows.append(DiffRow("replace", i + 1, a[i], j + 1, b[j]))
            elif i is not None:
                rows.append(DiffRow("delete", i + 1, a[i], None, None))
            elif j is not None:
                rows.append(DiffRow("insert", None, None, j + 1, b[j]))
    return rows


@dataclass(frozen=True)
class DiffStats:
    added: int
    removed: int
    changed: int

    @property
    def unchanged(self) -> bool:
        return not (self.added or self.removed or self.changed)


def diff_stats(rows: list[DiffRow]) -> DiffStats:
    return DiffStats(
        added=sum(r.kind == "insert" for r in rows),
        removed=sum(r.kind == "delete" for r in rows),
        changed=sum(r.kind == "replace" for r in rows),
    )
