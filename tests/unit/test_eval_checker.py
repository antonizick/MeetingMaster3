"""The eval checker's own rules (15g: a cloud model's owner headings are not malformed tasks)."""

from __future__ import annotations

import pytest

from tests.eval.checker import BULLET_RE, CHECKBOX_RE


@pytest.mark.parametrize(
    ("line", "bullet"),
    [
        ("- [ ] **Ana:** ship it (due: Friday) [01:00]", True),
        ("- ship it", True),
        ("* ship it", True),
        ("+ ship it", True),
        ("**Marcus Webb**", False),  # an owner heading (Haiku 5.5 on Action-Focused)
        ("**Unassigned:**", False),
        ("*Owner*", False),
    ],
)
def test_bold_owner_headings_are_not_bullets(line: str, bullet: bool) -> None:
    assert bool(BULLET_RE.match(line)) is bullet


def test_only_checkbox_bullets_pass_the_task_format() -> None:
    assert CHECKBOX_RE.match("- [ ] **Ana:** ship it")
    assert not CHECKBOX_RE.match("* ship it")


def test_a_task_without_its_checkbox_is_caught() -> None:
    """15g: a task line with no list marker at all used to slip past the format check."""
    from meetingmaster3.domain.note import Section
    from meetingmaster3.markdown.note_writer import build_note, render_note
    from meetingmaster3.templates.loader import load_library
    from tests.eval.checker import load_meetings, score_note

    meeting = next(m for m in load_meetings() if m.name == "launch-sync")
    template = load_library().get("action-focused")

    def score(tasks: str) -> bool | None:
        sections = [Section(id="action-items", title="Action Items", body_markdown=tasks)]
        note = render_note(build_note(meeting.meta(), sections))
        return score_note(note, meeting, template).checks.get("checkbox_format")

    assert score("- [ ] **Caleb:** Sync with the team (due: not stated) [29:23]") is True
    assert score("**Caleb:** Sync with the team (due: not stated) [29:23]") is False
    assert score("**Caleb**\n- [ ] **Caleb:** Sync (due: not stated) [29:23]") is True


def test_untimed_conversation_and_section_checks() -> None:
    """15m: an untimed eval conversation loads as an untimed transcript; ``expected.absent``
    and list-style ``expected.numbered`` score the sections they name."""
    from meetingmaster3.domain.note import Section
    from meetingmaster3.markdown.note_writer import build_note, render_note
    from meetingmaster3.templates.loader import load_library
    from tests.eval.checker import load_meetings, score_note

    meeting = next(m for m in load_meetings() if m.name == "chat-photo-backup-plan")
    assert meeting.transcript.timed is False
    assert all(s.start == 0 for s in meeting.transcript.segments)
    template = load_library().get("create-project-plan")

    def checks(decisions: str, milestones: str) -> dict[str, bool]:
        bodies = {"decisions": decisions, "milestones": milestones}
        sections = [
            Section(id=sec.id, title=sec.title, body_markdown=bodies.get(sec.id, "x"))
            for sec in template.sections
        ]
        note = render_note(build_note(meeting.meta(), sections))
        return score_note(note, meeting, template).checks

    three = "1. **Install:** done\n2. **Phones:** done\n3. **Backup:** done"
    good = checks("1. **Use Immich on the NUC**", three)
    assert good["absent_rejected-not-decided"] is True
    assert good["numbered_phase-count"] is True
    bad = checks("1. **Use PhotoPrism**", "1. **Install:** done\n   2. nested")
    assert bad["absent_rejected-not-decided"] is False
    assert bad["numbered_phase-count"] is False
