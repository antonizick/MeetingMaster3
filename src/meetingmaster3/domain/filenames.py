"""Guess a meeting date, time and title from a recorder's audio filename (spec §3, step 2; R25).

This only pre-fills the upload form; the user can always edit the result.

Dates are tried in this order (ADR-0031):

1. year first: ``2026-10-11``, ``20261011_143000``, ``2026.10.11`` (with an optional time);
2. US numeric with a year: ``09-22-2026``, ``9-22-26``;
3. a month name: ``Sep 22``, ``Sept 22nd``, ``September 22, 2026``, ``22 Sep``;
4. month and day only: ``09-22``, ``9-22``, ``09_22``, ``09.22``.

Numbers are read month first (the US order). They are read day first only when the first number
is above 12 and the second is not (``22-09``). A date without a year takes the current year in the
server's local time zone, or the previous year when that would put the recording more than one
day in the future (``12-30`` seen on 2027-01-02 is 2026-12-30).
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

# Not glued to letters or digits on either side ("v2-10", "x09-22", "09-221" are not dates), and
# not one part of a longer dotted or dashed number ("1.2.3", "10-12-14-16").
_BEFORE = r"(?<![A-Za-z0-9])(?<![0-9][-_.:])"
_AFTER = r"(?![A-Za-z0-9])(?![-_.:]\d)"

_MDY_RE = re.compile(
    _BEFORE + r"(?P<a>\d{1,2})(?P<sep>[-_.])(?P<b>\d{1,2})(?P=sep)(?P<y>\d{4}|\d{2})" + _AFTER
)
_MD_RE = re.compile(_BEFORE + r"(?P<a>\d{1,2})(?P<sep>[-_.])(?P<b>\d{1,2})" + _AFTER)

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}  # fmt: skip
_MONTH = (
    r"(?P<mon>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
    r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
)
_DAY = r"(?P<d>[0-3]?\d)(?:st|nd|rd|th)?"
_YEAR = r"(?:,?[\s_-]+(?P<y>(?:19|20)\d\d))?"
_NAMED_RES = (
    re.compile(
        r"(?<![A-Za-z])" + _MONTH + r"[\s_-]*" + _DAY + r"(?![\d:])" + _YEAR + r"(?!\d)", re.I
    ),
    re.compile(_BEFORE + _DAY + r"[\s_-]*" + _MONTH + r"(?![A-Za-z])" + _YEAR + r"(?!\d)", re.I),
)

# Words that make a number pair a count, a range or a version, not a date: "Part 1-2",
# "Top 10-15", "Ep 3.4", "5-10 min", "3-4 people".
_COUNT_BEFORE_RE = re.compile(
    r"(?:\b(?:part|pt|top|ep|episode|vol|volume|ch|chapter|session|round|week|wk|no|page|pp|p"
    r"|ver|version|release|step|steps|level|grade|ages?|score)|#)\s*$",
    re.I,
)
_COUNT_AFTER_RE = re.compile(
    r"^\s*(?:min|mins|minutes?|hrs?|hours?|secs?|seconds?|days?|weeks?|people|persons?|items?"
    r"|pages?|slides?|questions?|ideas?|players?|%)(?![A-Za-z])",
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


def _is_count(stem: str, m: re.Match[str]) -> bool:
    return bool(
        _COUNT_BEFORE_RE.search(stem[: m.start()]) or _COUNT_AFTER_RE.match(stem[m.end() :])
    )


def _month_day(a: int, b: int) -> tuple[int, int]:
    """Month first, unless only the day-first reading is possible."""
    return (b, a) if a > 12 and b <= 12 else (a, b)


def _date(year: int, month: int, day: int) -> dt.date | None:
    try:
        return dt.date(year, month, day)
    except ValueError:
        return None


def infer_year(month: int, day: int, today: dt.date) -> dt.date | None:
    """This year's ``month``-``day``, or last year's if this year's is over a day in the future."""
    candidate = _date(today.year, month, day)
    if candidate is not None and candidate <= today + dt.timedelta(days=1):
        return candidate
    if candidate is None and not (month == 2 and day == 29):
        return None  # impossible in any year
    # A future date (or 29 February in a non-leap year) means an earlier recording.
    return _date(today.year - 1, month, day)


def _find_date(stem: str, today: dt.date) -> tuple[dt.date, dt.time | None, re.Match[str]] | None:
    for m in _DATE_TIME_RE.finditer(stem):
        date = _date(int(m["y"]), int(m["m"]), int(m["d"]))
        if date is None:
            continue
        time = dt.time(int(m["H"]), int(m["M"]), int(m["S"] or 0)) if m["H"] else None
        return date, time, m
    for m in _MDY_RE.finditer(stem):
        month, day = _month_day(int(m["a"]), int(m["b"]))
        year = int(m["y"]) + (2000 if len(m["y"]) == 2 else 0)
        date = _date(year, month, day) if year >= 1990 else None
        if date is not None and not _is_count(stem, m):
            return date, None, m
    for pattern in _NAMED_RES:
        for m in pattern.finditer(stem):
            month = _MONTHS[m["mon"][:3].lower()]
            day = int(m["d"])
            date = _date(int(m["y"]), month, day) if m["y"] else infer_year(month, day, today)
            if date is not None:
                return date, None, m
    for m in _MD_RE.finditer(stem):
        month, day = _month_day(int(m["a"]), int(m["b"]))
        date = infer_year(month, day, today)
        if date is not None and not _is_count(stem, m):
            return date, None, m
    return None


def parse_filename(name: str, *, today: dt.date | None = None) -> FilenameInfo:
    """Extract ``(date, time, title)`` from names such as ``2026-10-11 Product Sync.m4a``,
    ``20261011_143000.wav``, ``Zoom_Recording_2026-10-11_14-30-00.mp4``,
    ``Product Sync-20261011_143000-Meeting Recording.mp4`` or ``09-22 Interview_ Ann.mp3``.
    Unknown parts are ``None``. ``today`` (the server's local date by default) fills in a
    missing year."""
    stem = PurePath(name.replace("\\", "/")).name
    if "." in stem:
        stem = stem.rsplit(".", 1)[0]

    date: dt.date | None = None
    time: dt.time | None = None
    rest = stem
    found = _find_date(stem, today or dt.date.today())
    if found is not None:
        date, time, m = found
        rest = stem[: m.start()] + " " + stem[m.end() :]

    # Recorders and browsers turn ":" and "|" into "_": "Interview_ Ann _ SOC" reads
    # "Interview: Ann | SOC". A free-standing "_" is a separator, a glued one is a space.
    title = re.sub(r"\s+_+\s+", " - ", rest)
    title = title.replace("_", " ")
    title = _NOISE_RE.sub(" ", title)
    title = re.sub(r"\(\s*\)", " ", title)
    title = re.sub(r"\s*-(?:\s*-)+\s*", " - ", title)
    title = " ".join(title.split()).strip(" -.,()")
    return FilenameInfo(date=date, time=time, title=title if re.search(r"\w", title) else None)
