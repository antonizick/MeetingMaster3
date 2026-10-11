"""Guess a meeting date, time and title from a recorder's audio filename (spec §3, step 2).

This only pre-fills the upload form; the user can always edit the result.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from pathlib import PurePath

_DATE_TIME_RE = re.compile(
    r"(?<!\d)(?P<y>199\d|20\d\d)(?P<sep>[-_.]?)(?P<m>\d\d)(?P=sep)(?P<d>\d\d)"
    r"(?:(?:[T_ -]|\s+at\s+)(?P<H>[01]\d|2[0-3])(?P<tsep>[-:._h ]?)(?P<M>[0-5]\d)"
    r"(?:(?P=tsep)(?P<S>[0-5]\d))?)?(?!\d)",
    re.I,
)

_NOISE_RE = re.compile(
    r"\b(?:new\s+recording(?:\s+\d+)?|meeting\s+recording|audio[\s_]only|zoom|recording|rec"
    r"|gmt(?:[+-]\d{1,4})?)\b",
    re.I,
)


@dataclass(frozen=True)
class FilenameInfo:
    date: dt.date | None = None
    time: dt.time | None = None
    title: str | None = None

    @property
    def when(self) -> dt.datetime | None:
        if self.date is None:
            return None
        return dt.datetime.combine(self.date, self.time or dt.time())


def parse_filename(name: str) -> FilenameInfo:
    """Extract ``(date, time, title)`` from names such as ``2026-10-11 Product Sync.m4a``,
    ``20261011_143000.wav``, ``Zoom_Recording_2026-10-11_14-30-00.mp4`` or
    ``Product Sync-20261011_143000-Meeting Recording.mp4``. Unknown parts are ``None``."""
    stem = PurePath(name.replace("\\", "/")).name
    if "." in stem:
        stem = stem.rsplit(".", 1)[0]

    date: dt.date | None = None
    time: dt.time | None = None
    rest = stem
    for m in _DATE_TIME_RE.finditer(stem):
        try:
            date = dt.date(int(m["y"]), int(m["m"]), int(m["d"]))
        except ValueError:
            continue
        if m["H"]:
            time = dt.time(int(m["H"]), int(m["M"]), int(m["S"] or 0))
        rest = stem[: m.start()] + " " + stem[m.end() :]
        break

    title = rest.replace("_", " ")
    title = _NOISE_RE.sub(" ", title)
    title = re.sub(r"\(\s*\)", " ", title)
    title = re.sub(r"\s*-(?:\s*-)+\s*", " - ", title)
    title = " ".join(title.split()).strip(" -.,()")
    return FilenameInfo(date=date, time=time, title=title if re.search(r"\w", title) else None)
