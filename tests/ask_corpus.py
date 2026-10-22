"""The synthetic meeting corpus for the Ask agent (Phase 15j): 15i's seven meetings
(``tests/search_corpus.py``) plus a Meeting Context section stating people's roles in the three
"money spent beyond the plan" meetings, and an eighth decoy meeting that talks about a budget
without overspending it. Written into a temporary vault by the tests and ``tests/eval/ask_eval.py``.

The questions and their expected answers are in :data:`QUESTIONS`. People, companies and numbers
are invented; CC0.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
from dataclasses import dataclass
from pathlib import Path

from tests import search_corpus as sc

CONTEXT_ID = "meeting-context"
CONTEXT_TITLE = "Meeting Context"

ROLES = {
    "Dana Whitfield": "Chief Financial Officer",
    "Raj Patel": "VP of Engineering",
    "Mei Lin": "Procurement Manager",
    "Tom Becker": "Platform Team Lead",
    "Sofia Alvarez": "People Operations Lead",
}

_CONTEXTS = {
    "finance": (
        "- **Purpose:** review third-quarter spending against the budget.\n"
        "- **Dana Whitfield:** Chief Financial Officer; presented the quarter's numbers.\n"
        "- **Raj Patel:** VP of Engineering; owns the engineering cost centre.\n"
        "- **Mei Lin:** Procurement Manager; attended for the contractor contracts."
    ),
    "platform": (
        "- **Purpose:** weekly platform review.\n"
        "- **Raj Patel:** VP of Engineering; chaired the meeting.\n"
        "- **Tom Becker:** Platform Team Lead; presented the hosting bill."
    ),
    "vendor": (
        "- **Purpose:** prepare the analytics vendor contract renewal.\n"
        "- **Mei Lin:** Procurement Manager; runs the renewal.\n"
        "- **Dana Whitfield:** Chief Financial Officer."
    ),
}

DECOY = sc.Meeting(
    key="offsite",
    id=sc._id(8),
    title="Team Offsite Planning",
    date=dt.datetime(2026, 9, 25, 10, 0),
    speakers={"SPEAKER_00": "Sofia Alvarez", "SPEAKER_01": "Tom Becker"},
    participants=("Sofia Alvarez", "Tom Becker"),
    sections=(
        (
            CONTEXT_ID,
            CONTEXT_TITLE,
            "- **Purpose:** plan the October team offsite.\n"
            "- **Sofia Alvarez:** People Operations Lead; organises the offsite.\n"
            "- **Tom Becker:** Platform Team Lead.",
        ),
        (
            "summary",
            "Summary Succinct",
            "The two-day offsite in Lisbon was planned; the agenda has a hackathon and a "
            "planning workshop.",
        ),
        (
            "discussion",
            "Discussion",
            "- Sofia Alvarez booked the venue and the team dinner.\n"
            "- Tom Becker will run the hackathon on the second day.",
        ),
    ),
    lines=(
        ("SPEAKER_00", "The venue and dinner are booked, and the plan fits the offsite budget."),
        ("SPEAKER_01", "I will run the hackathon on the second day."),
    ),
)


def _with_context(m: sc.Meeting) -> sc.Meeting:
    body = _CONTEXTS.get(m.key)
    if body is None:
        return m
    return dataclasses.replace(m, sections=((CONTEXT_ID, CONTEXT_TITLE, body), *m.sections))


STATED_ROLES = frozenset({*_CONTEXTS, "offsite"})
"""Meetings whose Meeting Context states people's roles (the eval checks roles only there)."""
MEETINGS: tuple[sc.Meeting, ...] = (*(_with_context(m) for m in sc.MEETINGS), DECOY)
TOPIC = sc.TOPIC
"""The meetings about money spent beyond the plan (finance, platform, vendor)."""


def files() -> dict[str, str]:
    out = {}
    for m in MEETINGS:
        out[f"{sc.MEETINGS_DIR}/{m.stem}.md"] = sc.note_text(m)
        out[f"{sc.MEETINGS_DIR}/{m.stem}.transcript.md"] = sc.transcript_text(m)
    return out


def write_vault(root: Path) -> Path:
    (root / ".obsidian").mkdir(parents=True, exist_ok=True)
    for rel, text in files().items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="")
    return root.resolve()


def by_key(key: str) -> sc.Meeting:
    return next(m for m in MEETINGS if m.key == key)


@dataclass(frozen=True)
class Question:
    key: str
    text: str
    meetings: tuple[str, ...]
    """Keys of the meetings that answer it (the count is their number)."""
    people: tuple[str, ...] = ()
    """People who must appear as taking part in the topic (in at least one row)."""


QUESTIONS: tuple[Question, ...] = (
    Question(
        "overspend",
        "How many times have we discussed going over budget? Who was principally in those "
        "discussions and what was their role? Also create a table of all of the meetings and "
        "all of the dates and all of the attendees that have participated in discussions "
        "about this topic.",
        TOPIC,
        ("Dana Whitfield", "Raj Patel", "Tom Becker"),
    ),
    Question(
        "paraphrase",
        "Which meetings talked about money we spent beyond what we had expected?",
        TOPIC,
    ),
    Question(
        "hiring",
        "When did we talk about recruiting new engineers, and who is doing what?",
        ("hiring",),
        ("Sofia Alvarez", "Tom Becker"),
    ),
    Question(
        "outage",
        "Did we ever discuss the login outage? What caused it?",
        ("incident",),
    ),
    Question(
        "launch",
        "What did we decide about the date of the mobile app launch?",
        ("release",),
    ),
    Question("none", "Have we discussed moving the office to Berlin?", ()),
)
