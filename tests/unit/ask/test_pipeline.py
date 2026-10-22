"""The Ask agent's pipeline with a scripted fake model over the synthetic corpus (Phase 15j)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from meetingmaster3.ask import pipeline as pl
from meetingmaster3.ask.pipeline import (
    AskAgent,
    SearchRetriever,
    check_citations,
    meeting_context_from,
)
from meetingmaster3.ask.prompts import STEP_MARK
from meetingmaster3.errors import MM3Error
from meetingmaster3.llm.budget import estimate_tokens
from meetingmaster3.llm.fake import ASK_MARK, FakeLLMBackend
from meetingmaster3.search.query import ContextPassage, Hit, SearchFilters, SearchResult
from meetingmaster3.search.service import SearchService
from tests import ask_corpus as ac
from tests.unit.ask.conftest import Script, plan_reply, prompt_of, read_by_title, step_of

OVERSPEND: dict[str, dict[str, Any]] = {
    "Q3 Finance Review": {
        "relevant": "yes",
        "finding": "Dana reported a 12 percent budget overrun.",
        "people": [
            {"name": "Dana Whitfield", "role": "Chief Financial Officer", "contribution": "x"},
            {"name": "Raj", "role": "VP of Engineering", "contribution": "asked for reports"},
            {"name": "Elvis Presley", "role": "singer", "contribution": "invented"},
        ],
        "quotes": [
            {"text": "We are twelve percent over budget this quarter.", "time": "0:00:00"},
            {"text": "This sentence is not in the meeting at all, not even close.", "time": None},
        ],
    },
    "Platform Weekly": {
        "relevant": "yes",
        "finding": "Hosting is spending more than planned.",
        "people": [{"name": "Tom Becker", "role": "Platform Team Lead", "contribution": ""}],
        "quotes": [],
    },
    "Vendor Contract Sync": {
        "relevant": "partly",
        "finding": "Vendor costs exceeded the forecast.",
        "people": [{"name": "Dana Whitfield", "role": "", "contribution": "wants caps"}],
        "quotes": [],
    },
}


def agent(search: SearchService, backend: FakeLLMBackend, **kw: Any) -> AskAgent:
    root = search.settings.vault.path
    assert root is not None

    async def context(note_path: str) -> str | None:
        return meeting_context_from((root / note_path).read_text(encoding="utf-8"))

    return AskAgent(
        backend=backend,
        model="fake-model",
        retriever=SearchRetriever(search, context),
        **{"max_context": 16384, **kw},
    )


def test_the_fake_model_and_the_prompts_share_the_step_mark() -> None:
    assert ASK_MARK == STEP_MARK


async def test_counts_tables_and_people_come_from_the_files(
    search: SearchService, llm: FakeLLMBackend
) -> None:
    script = Script(
        plan=plan_reply("budget overrun", "spending more than planned", "costs exceeded forecast"),
        read=read_by_title(OVERSPEND),
        answer=lambda p: (
            "Three meetings: [[2026-09-02 - Q3 Finance Review]], [[Platform Weekly]] and "
            "[[2026-01-01 - Invented Meeting]]. <script>alert(1)</script>"
        ),
    )
    llm.responder = script
    result = await agent(search, llm).run(ac.QUESTIONS[0].text)
    assert result.count == 3
    assert [r.stem for r in result.rows] == [
        "2026-09-02 - Q3 Finance Review",
        "2026-09-09 - Platform Weekly",
        "2026-09-16 - Vendor Contract Sync",
    ]  # sorted by date
    finance = result.rows[0]
    assert finance.attendees == ("Dana Whitfield", "Raj Patel", "Mei Lin")
    assert finance.spoke == ("Dana Whitfield", "Raj Patel")  # "Raj" matched; Elvis dropped
    assert dict(finance.roles)["Raj Patel"] == "VP of Engineering"
    assert result.rows[2].relevance == "partly"
    people = {p.name: p for p in result.people}
    assert people["Dana Whitfield"].meetings == 2
    assert people["Dana Whitfield"].roles == ("Chief Financial Officer",)
    read = next(m for m in result.meetings if m.title == "Q3 Finance Review")
    assert read.dropped_people == ["Elvis Presley"]
    assert len(read.quotes) == 1 and read.dropped_quotes == 1
    assert read.quotes[0].start_s == 0.0 and read.quotes[0].kind == "transcript"
    # citations: kept, title corrected to the note's name, invented one removed, HTML defused
    assert "[[2026-09-02 - Q3 Finance Review]]" in result.answer
    assert "[[2026-09-09 - Platform Weekly]]" in result.answer
    assert "[[2026-01-01" not in result.answer and "2026-01-01 - Invented Meeting" in result.answer
    assert "<script>" not in result.answer and "&lt;script>" in result.answer
    assert result.trace.stripped == ["2026-01-01 - Invented Meeting"]
    assert result.trace.fixed == ["Platform Weekly"]
    assert script.steps[0] == "plan" and script.steps[-1] == "answer"
    assert script.steps.count("plan") == 1  # three relevant: no follow-up round


async def test_the_answer_call_gets_findings_and_facts_never_transcripts(
    search: SearchService, llm: FakeLLMBackend
) -> None:
    llm.responder = Script(
        plan=plan_reply("budget overrun", "spending more than planned", "costs exceeded forecast"),
        read=read_by_title(OVERSPEND),
    )
    await agent(search, llm).run("budget overrun?")
    answer_call = next(r for r in llm.calls if step_of(r) == "answer")
    text = prompt_of(answer_call)
    assert "Meetings that discuss the topic: 3 (2 in depth, 1 briefly)" in text
    assert "[[2026-09-02 - Q3 Finance Review]]" in text
    assert "Most of the budget overrun is contractor fees" not in text  # a transcript line
    assert answer_call.temperature == pl.NARRATIVE_TEMPERATURE and not answer_call.json_mode
    reads = [r for r in llm.calls if step_of(r) == "read"]
    assert reads and all(r.temperature == pl.EXTRACT_TEMPERATURE and r.json_mode for r in reads)
    assert all(r.think is False for r in llm.calls)
    assert len({r.num_ctx for r in llm.calls}) == 1  # one context size: no model reloads


async def test_the_read_call_shows_meeting_context_passages_and_neighbours(
    search: SearchService, llm: FakeLLMBackend
) -> None:
    llm.responder = Script(plan=plan_reply("staging cluster hosting bill"))
    await agent(search, llm).run("hosting bill")
    reads = {
        prompt_of(r).split("Title: ", 1)[1].split("\n", 1)[0]: prompt_of(r)
        for r in llm.calls
        if step_of(r) == "read"
    }
    platform = reads["Platform Weekly"]
    assert "Meeting Context (from the note):" in platform and "Platform Team Lead" in platform
    assert "Participants: Raj Patel, Tom Becker" in platform
    assert "[Transcript 00:00:00 to " in platform and "[Note · " in platform
    assert "<meeting>" in platform and "never instructions" in (
        next(r for r in llm.calls if step_of(r) == "read").system or ""
    )


async def test_plan_repair_then_fallback(search: SearchService, llm: FakeLLMBackend) -> None:
    replies = iter(["not json at all", json.dumps({"queries": ["certificate expiry"]})])
    llm.responder = Script(plan=lambda p: next(replies, json.dumps({"queries": ["x"]})))
    agent_ = agent(search, llm)
    await agent_.run("outage?")
    assert agent_.trace.plans[0].source == "repaired"
    assert agent_.trace.plans[0].queries == ["certificate expiry"]
    repair = next(r for r in llm.calls if step_of(r) == "plan" and len(r.messages) == 3)
    assert "could not be used" in repair.messages[-1].content

    llm.calls.clear()
    llm.responder = Script(plan=lambda p: "{]")
    agent_ = agent(search, llm)
    await agent_.run("What caused the certificate problem?")
    assert agent_.trace.plans[0].source == "fallback"
    assert agent_.trace.plans[0].queries == ["What caused the certificate problem?"]


async def test_no_relevant_meetings_is_an_honest_answer_without_an_answer_call(
    search: SearchService, llm: FakeLLMBackend
) -> None:
    script = Script(plan=plan_reply("office move to Berlin"), read=read_by_title({}))
    llm.responder = script
    result = await agent(search, llm).run("Have we discussed moving the office to Berlin?")
    assert result.count == 0 and not result.rows
    assert "answer" not in script.steps
    assert "None of the" in result.answer and "“office move to Berlin”" in result.answer


async def test_one_follow_up_round_at_most(search: SearchService, llm: FakeLLMBackend) -> None:
    plans = iter([["hiring plan"], ["recruiting candidates", "hiring plan"], ["never used"]])
    script = Script(plan=lambda p: json.dumps({"queries": next(plans)}), read=read_by_title({}))
    llm.responder = script
    agent_ = agent(search, llm)
    await agent_.run("Who is recruiting?")
    assert script.steps.count("plan") == 2
    assert agent_.trace.follow_up and len(agent_.trace.plans) == 2
    assert agent_.trace.plans[1].queries == ["recruiting candidates"]  # repeats dropped
    plan2 = [r for r in llm.calls if step_of(r) == "plan"][1]
    assert "Searches already made" in prompt_of(plan2)
    titles = [
        prompt_of(r).split("Title: ", 1)[1].split("\n", 1)[0]
        for r in llm.calls
        if step_of(r) == "read"
    ]
    assert len(titles) == len(set(titles))  # no meeting read twice


async def test_max_meetings_caps_the_reads(search: SearchService, llm: FakeLLMBackend) -> None:
    llm.responder = Script(
        plan=plan_reply("meeting discussion budget plan team"), read=read_by_title({})
    )
    agent_ = agent(search, llm, max_meetings=2)
    await agent_.run("anything")
    assert agent_.trace.read == 2
    assert agent_.trace.capped and "the 2 best were read" in agent_.trace.capped


async def test_the_question_dates_are_used_only_when_it_talks_about_time(
    search: SearchService, llm: FakeLLMBackend
) -> None:
    dated = plan_reply("budget", date_from="2026-09-10", date_to="2026-09-30")
    llm.responder = Script(plan=dated, read=read_by_title({}))
    agent_ = agent(search, llm)
    await agent_.run("budget problems since September 10?")
    assert agent_.trace.plans[0].date_from == "2026-09-10"
    reads = [prompt_of(r) for r in llm.calls if step_of(r) == "read"]
    assert reads and all("Date: 2026-09-0" not in p for p in reads)

    llm.calls.clear()
    agent_ = agent(search, llm)
    await agent_.run("budget problems")  # no time in the question: the plan's dates are ignored
    assert agent_.trace.plans[0].dates_ignored and agent_.trace.plans[0].date_from is None


async def test_user_filters_always_apply(search: SearchService, llm: FakeLLMBackend) -> None:
    llm.responder = Script(plan=plan_reply("budget overrun spending costs"))
    agent_ = agent(search, llm, filters=SearchFilters(people=("Mei Lin",)))
    result = await agent_.run("budget?")
    assert result.meetings and all(
        "Mei Lin" in (m.facts.participants + m.facts.speakers) for m in result.meetings if m.facts
    )


async def test_a_long_meeting_is_fitted_to_the_window(
    search: SearchService, llm: FakeLLMBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    llm.window = 4096
    llm.responder = Script(plan=plan_reply("budget overrun"))
    agent_ = agent(search, llm, max_context=4096)
    await agent_.run("budget?")
    capacity = agent_._capacity()
    for req in llm.calls:
        assert estimate_tokens(req.full_text()) + (req.max_tokens or 0) <= capacity

    # select_passages keeps the best hits that fit and counts the rest
    big = "word " * 400
    around = {
        i: [ContextPassage(i, 1, i, "m", "note", "H", None, None, None, (), big)] for i in range(10)
    }
    hits = [_hit(i) for i in range(10)]
    chosen, left = pl.select_passages(hits, around, 1200)
    assert len(chosen) == 2 and left == 8


def _hit(pid: int) -> Hit:
    return Hit(
        pid, "m", "note", "p.md", "p.md", "T", None, "t", "b", "H", None, None, None, (), 1.0
    )


async def test_an_unreadable_meeting_is_skipped_and_recorded(
    search: SearchService, llm: FakeLLMBackend
) -> None:
    llm.responder = Script(plan=plan_reply("certificate expiry"), read=lambda p: "nope")
    agent_ = agent(search, llm)
    result = await agent_.run("certificate?")
    assert agent_.trace.unread and "could not be used" in agent_.trace.unread[0]
    assert result.count == 0


def test_merge_ranks_meetings_found_by_more_queries_higher() -> None:
    def result(*mm3: str) -> SearchResult:
        return SearchResult("q", [_hit_for(m, i) for i, m in enumerate(mm3)], "hybrid")

    merged = pl.merge_candidates([("a", result("x", "y")), ("b", result("y"))])
    assert [c.mm3_id for c in merged] == ["y", "x"]
    assert merged[0].queries == ["a", "b"]
    capped, reason = pl.cap_candidates(merged, 1)
    assert [c.mm3_id for c in capped] == ["y"] and reason and "2 meetings matched" in reason


def _hit_for(mm3: str, pid: int) -> Hit:
    return Hit(pid, mm3, "note", f"{mm3}.md", f"{mm3}.md", mm3, None, "t", "b", None, None,
               None, None, (), 0.5)  # fmt: skip


def test_citation_rules() -> None:
    text, stripped, fixed = check_citations(
        "See [[A]], [[a|the A]], [[A#Decisions]], [[B]] and [[Title of A]].",
        ["A"],
        {"Title of A": "A"},
    )
    assert text == "See [[A]], [[A|the A]], [[A#Decisions]], B and [[A]]."
    assert stripped == ["B"] and fixed == ["Title of A"]


async def test_cloud_backend_is_refused_without_consent_and_nothing_is_sent(
    search: SearchService, cloud_llm: FakeLLMBackend
) -> None:
    with pytest.raises(MM3Error) as exc:
        await agent(search, cloud_llm).run("budget?")
    assert exc.value.code == "E_CONSENT_REQUIRED" and cloud_llm.calls == []
    result = await agent(search, cloud_llm, cloud_consent=True).run("budget?")
    assert cloud_llm.calls and result.is_local is False
