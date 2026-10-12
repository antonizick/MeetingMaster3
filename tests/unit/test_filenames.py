"""Dates from file names without a year, and US forms (Phase 15a, R25, ADR-0031)."""

from __future__ import annotations

import datetime as dt

import pytest

from meetingmaster3.domain.filenames import infer_year, parse_filename

TODAY = dt.date(2026, 10, 12)
NICK = "09-22 Interview_ Nick Antoncic - SOC Manager _ Cyber Defense Candidate.mp3"


@pytest.mark.parametrize(
    ("name", "date"),
    [
        # month and day only: the current year
        ("09-22 Sync.mp3", dt.date(2026, 9, 22)),
        ("9-22 Sync.mp3", dt.date(2026, 9, 22)),
        ("09_22 Sync.mp3", dt.date(2026, 9, 22)),
        ("09.22 Sync.mp3", dt.date(2026, 9, 22)),
        ("Sync 9-2.mp3", dt.date(2026, 9, 2)),
        ("Sync_09-22_final.mp4", dt.date(2026, 9, 22)),
        # day first only when it is the only reading
        ("22-09 Sync.mp3", dt.date(2026, 9, 22)),
        ("03-04 Sync.mp3", dt.date(2026, 3, 4)),
        # month names
        ("Sep 22 Sync.mp3", dt.date(2026, 9, 22)),
        ("Sept 22nd Sync.mp3", dt.date(2026, 9, 22)),
        ("September 22 Sync.mp3", dt.date(2026, 9, 22)),
        ("sync sept. 3rd.m4a", dt.date(2026, 9, 3)),
        ("22 Sep Sync.mp3", dt.date(2026, 9, 22)),
        ("Sync_22Sep.mp3", dt.date(2026, 9, 22)),
        ("Sync September 22, 2025.mp3", dt.date(2025, 9, 22)),
        ("Sync 1 Oct 2024.mp3", dt.date(2024, 10, 1)),
        # US numeric with a year
        ("09-22-2026 Sync.mp3", dt.date(2026, 9, 22)),
        ("9-22-26 Sync.mp3", dt.date(2026, 9, 22)),
        ("9.22.25 Sync.mp3", dt.date(2025, 9, 22)),
        ("22-09-2024 Sync.mp3", dt.date(2024, 9, 22)),
        # year first keeps priority over a later month-day
        ("2026-10-11 Sync 09-22.mp3", dt.date(2026, 10, 11)),
        # not dates
        ("02-30 Sync.mp3", None),
        ("13-13 Sync.mp3", None),
        ("Standup 14-30.mp3", None),  # a time
        ("Release v2-10 demo.mp3", None),  # a version
        ("Build 1.2.3 review.mp3", None),  # a version
        ("1-on-1 with Ann.mp3", None),
        ("Top 10-12 ideas.mp3", None),  # a count
        ("Part 1-2.mp3", None),
        ("Warmup 5-10 min.mp3", None),
        ("Panel 3-4 people.mp3", None),
        ("Call 123-45.mp3", None),  # glued to more digits
        ("Call 09-221.mp3", None),
        ("Room x09-22.mp3", None),
        ("10-12-14-16 numbers.mp3", None),
        ("Sync 12:30.mp3", None),
        ("May I ask.mp3", None),
        ("Retro Mar 45.mp3", None),
    ],
)
def test_dates_from_file_names(name: str, date: dt.date | None) -> None:
    assert parse_filename(name, today=TODAY).date == date


def test_nicks_file_name() -> None:
    info = parse_filename(NICK, today=TODAY)
    assert info.date == dt.date(2026, 9, 22)
    assert info.time is None
    assert info.title == "Interview Nick Antoncic - SOC Manager - Cyber Defense Candidate"


@pytest.mark.parametrize(
    ("name", "title"),
    [
        ("Sep 22 Weekly sync.mp3", "Weekly sync"),
        ("Weekly sync - 09.22.m4a", "Weekly sync"),
        ("Weekly_sync_9-22-26.m4a", "Weekly sync"),
        ("Budget _ Q3 _ final.mp3", "Budget - Q3 - final"),
        ("Interview_ Ann.mp3", "Interview Ann"),
    ],
)
def test_title_loses_the_date_and_stray_separators(name: str, title: str) -> None:
    assert parse_filename(name, today=TODAY).title == title


@pytest.mark.parametrize(
    ("month", "day", "today", "expected"),
    [
        (9, 22, dt.date(2026, 10, 12), dt.date(2026, 9, 22)),
        (10, 12, dt.date(2026, 10, 12), dt.date(2026, 10, 12)),  # today
        (10, 13, dt.date(2026, 10, 12), dt.date(2026, 10, 13)),  # tomorrow: time zones
        (10, 14, dt.date(2026, 10, 12), dt.date(2025, 10, 14)),  # further ahead: last year
        (12, 30, dt.date(2027, 1, 2), dt.date(2026, 12, 30)),  # the year rollover
        (1, 1, dt.date(2026, 12, 31), dt.date(2026, 1, 1)),  # the current year, never the next
        (2, 29, dt.date(2028, 3, 1), dt.date(2028, 2, 29)),  # leap year
        (2, 29, dt.date(2027, 3, 1), None),  # 2027 and 2026 are not leap years
        (2, 29, dt.date(2029, 3, 1), dt.date(2028, 2, 29)),  # the previous year is a leap year
        (2, 30, dt.date(2026, 10, 12), None),
    ],
)
def test_year_inference(month: int, day: int, today: dt.date, expected: dt.date | None) -> None:
    assert infer_year(month, day, today) == expected


def test_rollover_through_parse_filename() -> None:
    assert parse_filename("12-30 Sync.mp3", today=dt.date(2027, 1, 2)).date == dt.date(2026, 12, 30)


def test_default_today_is_the_local_date() -> None:
    today = dt.date.today()
    info = parse_filename(f"{today.month:02d}-{today.day:02d} Sync.mp3")
    assert info.date == today


def test_video_file_names_work_the_same() -> None:
    assert parse_filename("09-22 Demo.mkv", today=TODAY).date == dt.date(2026, 9, 22)
