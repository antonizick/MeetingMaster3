"""Validation of the model's JSON replies (Phase 15j)."""

from __future__ import annotations

import pytest

from meetingmaster3.ask.schema import AskParseError, Plan, Reading, parse_reply


def test_plan_is_normalised() -> None:
    plan = parse_reply(
        '```json\n{"queries": ["Budget", "budget", "  over   spend ", 3, null, "x"], '
        '"date_from": "2026-09-01T00:00", "date_to": "soon", "people": "Raj", '
        '"wants": ["Table", "count", "chart"], "topic": "money",}\n```',
        Plan,
    )
    assert plan.queries == ["Budget", "over spend", "3", "x"]
    assert plan.date_from == "2026-09-01" and plan.date_to is None
    assert plan.people == ["Raj"] and plan.wants == ["count", "table"] and plan.topic == "money"


def test_plan_needs_a_query() -> None:
    with pytest.raises(AskParseError, match="queries"):
        parse_reply('{"queries": []}', Plan)
    with pytest.raises(AskParseError, match="JSON"):
        parse_reply("I would search for budgets.", Plan)


def test_reading_tolerates_small_model_shapes() -> None:
    r = parse_reply(
        '<think>hmm</think>{"relevant": true, "finding": "x", "people": ["Dana", {"name": ""}, '
        '{"name": "Raj", "role": null}], "quotes": ["a quote", {"text": "b", "time": "[1:02:03]"}, '
        '{"text": "c", "time": "noon"}, "d"]}',
        Reading,
    )
    assert r.relevant == "yes"
    assert [p.name for p in r.people] == ["Dana", "Raj"] and r.people[1].role == ""
    assert [q.text for q in r.quotes] == ["a quote", "b", "c"]  # at most three
    assert r.quotes[1].time == "1:02:03" and r.quotes[2].time is None
    assert parse_reply('{"relevant": "Partially"}', Reading).relevant == "partly"
    with pytest.raises(AskParseError):
        parse_reply('{"relevant": "maybe"}', Reading)


def test_a_cut_off_reply_is_salvaged() -> None:
    r = parse_reply('{"relevant": "no", "finding": "", "people": [{"name": "A"}], "quo', Reading)
    assert r.relevant == "no" and r.people[0].name == "A"
