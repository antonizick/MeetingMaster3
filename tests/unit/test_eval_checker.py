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
