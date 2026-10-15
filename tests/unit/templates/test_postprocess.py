"""Section post-processing, deadline dates, task cues and the owner guard."""

from __future__ import annotations

import datetime as dt

import pytest

from meetingmaster3.domain.note import Section
from meetingmaster3.llm.budget import Turn
from meetingmaster3.templates.cues import Cue, classify, guard_owners, task_cues
from meetingmaster3.templates.postprocess import (
    EMPTY_BODY,
    annotate_due_dates,
    clean_section,
    resolve_deadline,
)

TUESDAY = dt.date(2026, 10, 6)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Plain text.", "Plain text."),
        ("<think>hmm, let me see</think>\nThe answer.", "The answer."),
        ("<think>never closed because the limit hit", EMPTY_BODY),
        ("```markdown\n- one\n- two\n```", "- one\n- two"),
        ("## Summary\n\nThe team agreed.", "The team agreed."),
        ("# Anything\nBody", "Body"),
        ("### Summary\nBody", "Body"),  # a level-3 heading equal to the title
        ("### Details\nBody", "### Details\nBody"),  # other level-3 headings stay
        ("**Summary:**\nBody", "Body"),
        ("Here is the section:\n\nBody", "Body"),
        ("Sure! Here's the summary:\nBody", "Body"),
        ("Body\n## Sub heading\nMore", "Body\n### Sub heading\nMore"),
        ("<!-- mm3:section:summary -->\nBody\n<!-- /mm3:section:summary -->", "Body"),
        ("Body <!-- mm3:section:x --> inline", "Body  inline"),
        ("\n\n\nBody\n\n\n\nMore\n\n", "Body\n\nMore"),
        ("", EMPTY_BODY),
        ("   \n  ", EMPTY_BODY),
        ("line\r\nend", "line\nend"),
    ],
)
def test_clean_section(raw: str, expected: str) -> None:
    out = clean_section(raw, title="Summary")
    assert out == expected
    Section(id="summary", title="Summary", body_markdown=out)  # always a valid section body


def test_tasks_become_checkboxes() -> None:
    raw = (
        "* **Alice:** Send the deck (due: Friday)\n"
        "1. **Bob:** Book the room (due: not stated)\n"
        "- [x] **Cara:** Already done\n"
        "[ ] **Dan:** Loose checkbox\n"
        "  - a nested note stays a note\n"
        "Some prose line."
    )
    out = clean_section(raw, title="Action Items", fmt="tasks", meeting_day=TUESDAY)
    assert out.split("\n") == [
        "- [ ] **Alice:** Send the deck (due: Friday, 2026-10-09)",
        "- [ ] **Bob:** Book the room (due: not stated)",
        "- [x] **Cara:** Already done",
        "- [ ] **Dan:** Loose checkbox",
        "  - a nested note stays a note",
        "Some prose line.",
    ]


def test_task_sentinel_is_not_a_checkbox() -> None:
    assert clean_section("No action items were agreed.", fmt="tasks") == (
        "No action items were agreed."
    )


def test_bullets_format() -> None:
    assert clean_section("* a\n+ b\n  * c", fmt="bullets") == "- a\n- b\n  - c"


@pytest.mark.parametrize(
    ("said", "date"),
    [
        ("Friday", "2026-10-09"),
        ("by Friday", "2026-10-09"),
        ("Tuesday", "2026-10-13"),  # the meeting's own weekday means next week
        ("next Wednesday", "2026-10-14"),
        ("Wednesday next week", "2026-10-14"),
        ("today", "2026-10-06"),
        ("end of day", "2026-10-06"),
        ("end of day tomorrow", "2026-10-07"),
        ("this week", None),
        ("Friday or Monday", None),
        ("2026-10-30", None),
        ("end of Q3", None),
        ("not stated", None),
    ],
)
def test_resolve_deadline(said: str, date: str | None) -> None:
    got = resolve_deadline(said, TUESDAY)
    assert (got.isoformat() if got else None) == date


def test_annotate_keeps_trailing_parts() -> None:
    line = "- [ ] **X:** y (due: Thursday; depends on Bob) [01:00]"
    assert annotate_due_dates(line, TUESDAY) == (
        "- [ ] **X:** y (due: Thursday, 2026-10-08; depends on Bob) [01:00]"
    )


@pytest.mark.parametrize(
    ("sentence", "kind"),
    [
        ("I'll send the report tomorrow.", "commits"),
        ("I can take that.", "commits"),
        ("Tom, can you email them?", "asks"),
        ("We should update the status page.", "suggests"),
        ("Somebody should raise it with support.", "suggests"),
        ("It's not something I can do.", "declines"),
        ("I won't be able to do that, I'm going to be away.", "declines"),
        ("The beta went out on Monday.", None),
    ],
)
def test_classify(sentence: str, kind: str | None) -> None:
    assert classify(sentence) == kind


def test_task_cues_split_sentences_and_keep_order() -> None:
    turns = [
        Turn("Ann", "Thanks all. I'll draft the plan. We should also check the budget.", 5.0),
        Turn("Ben", "Sounds good.", 9.0),
    ]
    cues = task_cues(turns, lambda t: f"[{t.start:.0f}]")
    assert [c.render() for c in cues] == [
        "[5] Ann (commits to it): I'll draft the plan.",
        "[5] Ann (suggestion: no owner unless someone takes it on): We should also check the "
        "budget.",
    ]


CUES = [
    Cue("Marcus Webb", "commits", "I'll finish the billing migration script by Friday."),
    Cue("Marcus Webb", "suggests", "Also, we should update the status page template."),
    Cue("Priya Natarajan", "asks", "Tom, can you let Northwind know about the export change?"),
    Cue(
        "Daniel Ortiz", "declines", "Platform needs to set up the schedule, not something I can do."
    ),
]


def test_owner_guard_unassigns_only_contradicted_owners() -> None:
    body = "\n".join(
        [
            "- [ ] **Marcus Webb:** Finish the billing migration script (due: Friday)",
            "- [ ] **Marcus Webb:** Update the status page template before launch",
            "- [ ] **Tom Fischer:** Email Northwind about the export change",
            "- [ ] **Daniel:** Set up the weekend schedule for staging",
            "- [ ] **Unassigned:** Something else",
            "- [ ] **Grace Mensah:** Ask the platform team",  # no evidence either way: kept
            "Prose stays.",
        ]
    )
    out, changed = guard_owners(body, CUES)
    assert out.split("\n") == [
        "- [ ] **Marcus Webb:** Finish the billing migration script (due: Friday)",
        "- [ ] **Unassigned:** Update the status page template before launch",
        "- [ ] **Tom Fischer:** Email Northwind about the export change",
        "- [ ] **Unassigned:** Set up the weekend schedule for staging",
        "- [ ] **Unassigned:** Something else",
        "- [ ] **Grace Mensah:** Ask the platform team",
        "Prose stays.",
    ]
    assert len(changed) == 2


def test_owner_guard_keeps_owner_who_also_committed() -> None:
    cues = [
        Cue("Ann", "suggests", "We should rewrite the onboarding email."),
        Cue("Ann", "commits", "Actually I'll rewrite the onboarding email myself."),
    ]
    out, changed = guard_owners("- [ ] **Ann:** Rewrite the onboarding email", cues)
    assert changed == [] and out == "- [ ] **Ann:** Rewrite the onboarding email"


def test_owner_task_lines_without_a_list_marker_become_checkboxes() -> None:
    """15g: Haiku 5.5 on Bedrock wrote tasks as bold-owner lines with no ``- [ ]``."""
    raw = (
        "**Caleb:** Sync with the team on next steps. (due: not stated) [29:23]\n"
        "\n"
        "**Unassigned:** Evolve the SOC. (due: not stated) [22:18]\n"
        "**Marcus Webb**\n"
        "**Note:** owners were not always clear."
    )
    out = clean_section(raw, title="Action Items", fmt="tasks")
    assert out.split("\n") == [
        "- [ ] **Caleb:** Sync with the team on next steps. (due: not stated) [29:23]",
        "",
        "- [ ] **Unassigned:** Evolve the SOC. (due: not stated) [22:18]",
        "**Marcus Webb**",  # an owner heading stays a heading
        "**Note:** owners were not always clear.",  # no (due: ...): not a task
    ]
