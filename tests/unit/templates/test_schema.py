"""Template validation: good and bad files, with line numbers (template-format.md §6)."""

from __future__ import annotations

from pathlib import Path

import pytest

from meetingmaster3.templates.loader import builtin_files
from meetingmaster3.templates.schema import (
    DEFAULT_TEMPERATURES,
    parse_template,
    parse_template_file,
)
from tests.unit.templates.builtin_ids import BUILTIN_IDS

GOOD = """\
---
mm3-template: 1
id: tiny
name: Tiny
description: A small template.
tags: [test]
sections:
  - {id: summary, title: Summary, kind: narrative}
  - {id: action-items, title: Action Items, kind: extraction, format: tasks, temperature: 0.1}
  - {id: ai-recommendations, title: AI Recommendations, kind: narrative, max_tokens: 300}
params: {max_tokens_per_section: 500}
---
Free text for humans is ignored.

<!-- mm3:prompt:_system -->
Be brief.

<!-- mm3:prompt:summary -->
Summarise.

<!-- mm3:prompt:action-items -->
List tasks.

<!-- mm3:prompt:ai-recommendations -->
Recommend.
"""


def codes_and_lines(text: str) -> list[tuple[str, int]]:
    return [(i.code, i.line) for i in parse_template(text).issues]


def test_good_template_parses() -> None:
    report = parse_template(GOOD)
    assert report.ok and report.issues == []
    t = report.template
    assert t is not None
    assert t.id == "tiny" and t.tags == ("test",)
    assert [s.id for s in t.sections] == ["summary", "action-items", "ai-recommendations"]
    assert t.system_prompt == "Be brief."
    assert t.prompts == {
        "summary": "Summarise.",
        "action-items": "List tasks.",
        "ai-recommendations": "Recommend.",
    }
    summary, actions, recs = t.sections
    assert t.temperature(summary) == DEFAULT_TEMPERATURES["narrative"] == 0.4
    assert t.temperature(actions) == 0.1  # section override
    assert t.max_tokens(summary) == 500 and t.max_tokens(recs) == 300
    assert actions.format == "tasks"


def test_template_wide_temperature_override() -> None:
    t = parse_template(GOOD.replace("{max_tokens_per_section: 500}", "{temperature: 0.7}")).template
    assert t is not None
    assert t.temperature(t.sections[0]) == 0.7
    assert t.temperature(t.sections[1]) == 0.1  # the section's own value still wins


AI_RECOMMENDATIONS_EXCEPTIONS = {"board-governance-minutes"}  # formal record, no AI commentary


@pytest.mark.parametrize("path", builtin_files(), ids=lambda p: p.stem)
def test_builtin_templates_are_valid(path: Path) -> None:
    report = parse_template_file(path)
    assert report.ok, [str(i) for i in report.issues]
    assert not report.warnings, [str(i) for i in report.warnings]
    t = report.template
    assert t is not None and t.id == path.stem
    ids = [s.id for s in t.sections]
    assert len(ids) == len(set(ids))  # unique section ids
    assert set(t.prompts) == set(ids)
    if t.params.ai_recommendations:
        assert ids[-1] == "ai-recommendations"
    else:
        assert "ai-recommendations" not in ids and t.id in AI_RECOMMENDATIONS_EXCEPTIONS
    for section in t.sections:
        assert t.prompts[section.id].strip(), section.id
        if section.id == "action-items":
            assert section.format == "tasks"
        if section.format == "tasks":
            assert "**Unassigned:**" in t.prompts[section.id]  # the owner-guard structure line
    assert t.system_prompt.strip()


def test_builtin_library_has_24_templates() -> None:
    assert sorted(p.stem for p in builtin_files()) == sorted(BUILTIN_IDS)
    assert len(BUILTIN_IDS) == 24


def test_sensitive_templates_keep_their_guardrails() -> None:
    interview = parse_template_file(
        next(p for p in builtin_files() if p.stem == "job-interview-notes")
    ).template
    assert interview is not None
    text = interview.system_prompt.casefold()
    assert "protected characteristics" in text and "advisory" in text
    assert "advisory only" in interview.prompts["hiring-recommendation"].casefold()
    board = parse_template_file(
        next(p for p in builtin_files() if p.stem == "board-governance-minutes")
    ).template
    assert board is not None
    assert board.params.ai_recommendations is False
    assert "never infer" in board.system_prompt.casefold()
    # Default Notes is used for interviews too (ADR-0039): same rules, no hiring decision.
    default = parse_template_file(
        next(p for p in builtin_files() if p.stem == "default-notes")
    ).template
    assert default is not None
    text = default.system_prompt.casefold()
    assert "protected characteristics" in text and "hiring decision" in text
    # Create Project Plan (R33): the owner decides, the AI assistant only proposes and claims.
    plan = parse_template_file(
        next(p for p in builtin_files() if p.stem == "create-project-plan")
    ).template
    assert plan is not None
    text = " ".join(plan.system_prompt.casefold().split())
    assert "never present an assistant suggestion as decided" in text
    assert "facts to verify" in text and "unverified" in text
    assert "never invent" in text
    assert "only when the owner accepted it" in " ".join(
        plan.prompts["decisions"].casefold().split()
    )
    assert "unverified" in plan.prompts["facts-to-verify"].casefold()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("no frontmatter\n", [("no_frontmatter", 1)]),
        ("---\nid: x\n", [("frontmatter_unclosed", 1)]),
        ("---\nid: [unclosed\n---\n", [("yaml_error", 2)]),
        ("---\nid: x\nname: : :\n---\n", [("yaml_error", 3)]),
        ("---\n- a list\n---\n", [("schema_error", 1)]),
    ],
)
def test_structural_errors(text: str, expected: list[tuple[str, int]]) -> None:
    assert codes_and_lines(text) == expected


def test_schema_error_points_at_the_offending_line() -> None:
    bad = GOOD.replace("format: tasks", "format: checklist")
    assert codes_and_lines(bad) == [("schema_error", 9)]
    issue = parse_template(bad).issues[0]
    assert "sections.1.format" in issue.message


def test_missing_key_reported() -> None:
    bad = GOOD.replace("name: Tiny\n", "")
    report = parse_template(bad)
    assert [(i.code, "name" in i.message) for i in report.issues] == [("schema_error", True)]
    assert report.template_id == "tiny"  # still known, for the library listing


def test_bad_ids() -> None:
    assert codes_and_lines(GOOD.replace("id: tiny", "id: Tiny Template")) == [("schema_error", 3)]
    bad = GOOD.replace("{id: summary,", "{id: Summary!,")
    assert codes_and_lines(bad) == [("schema_error", 8)]


def test_unsupported_version() -> None:
    assert codes_and_lines(GOOD.replace("mm3-template: 1", "mm3-template: 2")) == [
        ("unsupported_version", 2)
    ]


def test_duplicate_and_reserved_section_ids() -> None:
    dup = GOOD.replace("{id: action-items,", "{id: summary,").replace(
        "<!-- mm3:prompt:action-items -->\nList tasks.\n", ""
    )
    assert ("duplicate_section_id", 9) in codes_and_lines(dup)
    reserved = GOOD.replace("{id: summary,", "{id: _system,")
    assert ("reserved_section_id", 8) in codes_and_lines(reserved)


def test_ai_recommendations_rules() -> None:
    not_last = GOOD.replace(
        "  - {id: action-items, title: Action Items, kind: extraction, format: tasks, "
        "temperature: 0.1}\n  - {id: ai-recommendations, title: AI Recommendations, kind: "
        "narrative, max_tokens: 300}\n",
        "  - {id: ai-recommendations, title: AI Recommendations, kind: narrative}\n"
        "  - {id: action-items, title: Action Items, kind: extraction, format: tasks}\n",
    )
    assert codes_and_lines(not_last) == [("ai_recommendations_not_last", 9)]

    missing = GOOD.replace(
        "  - {id: ai-recommendations, title: AI Recommendations, kind: narrative, "
        "max_tokens: 300}\n",
        "",
    ).replace("<!-- mm3:prompt:ai-recommendations -->\nRecommend.\n", "")
    assert codes_and_lines(missing) == [("ai_recommendations_missing", 7)]

    optional = missing.replace("max_tokens_per_section: 500", "ai_recommendations: false")
    assert parse_template(optional).ok

    disabled = GOOD.replace("max_tokens_per_section: 500", "ai_recommendations: false")
    assert codes_and_lines(disabled) == [("ai_recommendations_disabled", 10)]


def test_prompt_block_errors_have_marker_lines() -> None:
    no_prompt = GOOD.replace("<!-- mm3:prompt:summary -->\nSummarise.\n", "")
    assert codes_and_lines(no_prompt) == [("missing_prompt", 8)]

    no_system = GOOD.replace("<!-- mm3:prompt:_system -->\nBe brief.\n", "")
    assert codes_and_lines(no_system) == [("missing_prompt", 13)]

    unknown = GOOD + "\n<!-- mm3:prompt:nonsense -->\nHello.\n"
    assert codes_and_lines(unknown) == [("unknown_prompt", 27)]

    duplicate = GOOD + "\n<!-- mm3:prompt:summary -->\nAgain.\n"
    assert codes_and_lines(duplicate) == [("duplicate_prompt", 27)]

    empty = GOOD.replace("Summarise.", "")
    assert codes_and_lines(empty) == [("empty_prompt", 18)]

    malformed = GOOD.replace("<!-- mm3:prompt:summary -->", "<!-- mm3: prompt summary -->")
    issues = codes_and_lines(malformed)
    assert ("malformed_prompt_marker", 18) in issues and ("missing_prompt", 8) in issues


def test_unknown_keys_are_warnings() -> None:
    report = parse_template(GOOD.replace("tags: [test]", "tags: [test]\nauthor: Nick"))
    assert report.ok
    assert [(w.code, w.line, w.severity) for w in report.warnings] == [
        ("unknown_key", 7, "warning")
    ]


def test_crlf_and_bom_are_accepted() -> None:
    report = parse_template("﻿" + GOOD.replace("\n", "\r\n"))
    assert report.ok
    assert report.template is not None and report.template.prompts["summary"] == "Summarise."


def test_size_limit_and_unreadable(tmp_path: Path) -> None:
    big = tmp_path / "big.md"
    big.write_text(GOOD + "x" * 300_000, encoding="utf-8")
    assert [i.code for i in parse_template_file(big).issues] == ["file_too_large"]
    binary = tmp_path / "bin.md"
    binary.write_bytes(b"\xff\xfe\x00bad")
    assert [i.code for i in parse_template_file(binary).issues] == ["unreadable"]
