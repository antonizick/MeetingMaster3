"""Hybrid search: FTS5 escaping, vectors, fusion, filters and facts (Phase 15i)."""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from meetingmaster3.config.settings import Settings
from meetingmaster3.llm.fake import FakeLLMBackend
from meetingmaster3.search.embedder import prefixes, resolve
from meetingmaster3.search.index import Indexer
from meetingmaster3.search.query import (
    Searcher,
    SearchFilters,
    fts_query,
    group_by_meeting,
    make_snippet,
    passage_body,
    query_terms,
    rrf,
)
from meetingmaster3.search.store import SearchStore
from tests.search_corpus import TOPIC, by_key
from tests.unit.search.conftest import cloud_settings

TOPIC_IDS = {str(by_key(k).id) for k in TOPIC}


@pytest.fixture
async def indexed(indexer: Indexer, corpus_vault: Path) -> None:
    await indexer.update(corpus_vault)


# -- escaping --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('budget "overrun', '"budget" OR "overrun"'),
        ("budget NEAR overrun", '"budget" OR "near" OR "overrun"'),
        ("budget* -run title:secret (a OR b)", '"budget" OR "run" OR "title" OR "secret"'),
        ("the and of", None),
        ("", None),
        ("^^^ *** :::", None),
        ("Café 2026", '"café" OR "2026"'),
    ],
)
def test_fts_query_quotes_every_term(text: str, expected: str | None) -> None:
    assert fts_query(text) == expected


def test_very_long_input_is_capped() -> None:
    terms = query_terms(" ".join(f"word{i}" for i in range(500)) + " " + "x" * 5000)
    assert len(terms) == 32 and all(len(t) <= 64 for t in terms)


@settings(max_examples=150, deadline=None)
@given(st.text(max_size=300))
def test_no_user_text_breaks_the_word_search(text: str) -> None:
    store = SearchStore.open(":memory:")
    try:
        searcher = Searcher(store)
        match = fts_query(text)
        if match:
            assert searcher.word_search(match, SearchFilters(), 10) == []
    finally:
        store.close()


async def test_hostile_queries_never_raise(indexed: None, searcher: Searcher) -> None:
    for text in [
        '"',
        "NEAR(",
        "*",
        "-",
        "a:b",
        "((",
        ")",
        "'; DROP TABLE documents; --",
        "\x00",
        "🙂" * 50,
    ]:
        result = await searcher.query(text)
        assert result.mode in ("hybrid", "meaning", "words", "none")


# -- fusion and ranking ----------------------------------------------------------------------


def test_rrf_rewards_agreement() -> None:
    scores = rrf([[1, 2, 3], [3, 4]])
    assert scores[3] == pytest.approx(1 / 63 + 1 / 61)
    assert max(scores, key=scores.__getitem__) == 3


async def test_meaning_finds_the_topic_in_different_words(
    indexed: None, searcher: Searcher
) -> None:
    # The fake model's similarities are not calibrated like a real model's, so the margin (tuned
    # for nomic-embed-text) is switched off here; test_the_vector_margin covers it.
    result = await searcher.query(
        "Where did we spend more money than planned?", limit=30, vector_margin=None
    )
    assert result.mode == "hybrid"
    ranked = [m.mm3_id for m in result.group_by_meeting()]
    assert set(ranked[:3]) == TOPIC_IDS
    words = await searcher.query("Where did we spend more money than planned?", use_vectors=False)
    assert words.mode == "words"
    assert set(m.mm3_id for m in words.group_by_meeting()) < TOPIC_IDS  # words alone miss some


async def test_the_vector_margin_drops_weak_matches(indexed: None, searcher: Searcher) -> None:
    question = "Where did we spend more money than planned?"
    wide = await searcher.query(question, limit=50, vector_margin=None)
    narrow = await searcher.query(question, limit=50, vector_margin=0.05)
    assert len([h for h in narrow.hits if h.vector_rank]) < len(
        [h for h in wide.hits if h.vector_rank]
    )
    best = max(h.vector_score or 0 for h in narrow.hits)
    assert all(h.vector_score >= best - 0.05 for h in narrow.hits if h.vector_score is not None)


async def test_word_hits_carry_scores_ranks_and_a_highlighted_snippet(
    indexed: None, searcher: Searcher
) -> None:
    result = await searcher.query("certificate", limit=5)
    top = result.hits[0]
    assert (
        top.title == "Incident Retro" and top.word_rank is not None and top.word_score is not None
    )
    assert any(matched and text.lower().startswith("certificate") for text, matched in top.snippet)
    assert top.note_path and top.note_path.endswith("Incident Retro.md")


async def test_transcript_hits_have_times_and_speakers(indexed: None, searcher: Searcher) -> None:
    result = await searcher.query(
        "costs exceeded the forecast", filters=SearchFilters(kinds=("transcript",))
    )
    hit = result.hits[0]
    assert (hit.kind, hit.title, hit.start_s, hit.speakers) == (
        "transcript",
        "Vendor Contract Sync",
        0.0,
        ("Dana Whitfield", "Mei Lin"),
    )
    assert hit.label() == "Transcript · 00:00:00 · Dana Whitfield, Mei Lin"
    assert hit.note_path and hit.note_path.endswith("Vendor Contract Sync.md")


# -- filters ---------------------------------------------------------------------------------


async def test_date_and_person_filters(indexed: None, searcher: Searcher) -> None:
    q = "budget spending costs"
    after = await searcher.query(q, filters=SearchFilters(date_from="2026-09-10"))
    assert {m.title for m in after.group_by_meeting()} <= {
        "Vendor Contract Sync",
        "Release Planning",
        "Incident Retro",
        "Design Crit",
    }
    assert "Vendor Contract Sync" in {m.title for m in after.group_by_meeting()}
    before = await searcher.query(q, filters=SearchFilters(date_to="2026-09-05"))
    assert {m.title for m in before.group_by_meeting()} <= {"Q3 Finance Review", "Hiring Plan"}
    tom = await searcher.query(q, filters=SearchFilters(people=("tom",)))
    titles = {m.title for m in tom.group_by_meeting()}
    assert "Platform Weekly" in titles and "Q3 Finance Review" not in titles
    one = await searcher.query(q, filters=SearchFilters(mm3_ids=(str(by_key("vendor").id),)))
    assert {m.title for m in one.group_by_meeting()} == {"Vendor Contract Sync"}


async def test_a_like_wildcard_in_a_person_filter_is_literal(
    indexed: None, searcher: Searcher
) -> None:
    result = await searcher.query("budget", filters=SearchFilters(people=("%",)))
    assert result.hits == []


# -- fallbacks -------------------------------------------------------------------------------


async def test_words_only_without_an_embedder(indexed: None, store: SearchStore) -> None:
    result = await Searcher(store).query("certificate")
    assert result.mode == "words" and result.hits and result.reason


async def test_words_only_when_the_index_has_no_vectors(
    store: SearchStore, search_settings: Settings, corpus_vault: Path, fake: FakeLLMBackend
) -> None:
    await Indexer(store, search_settings).update(corpus_vault)  # no embedder: words only
    result = await Searcher(
        store, lambda: resolve(search_settings, ["ollama"], lambda n: fake)
    ).query("certificate")
    assert result.mode == "words" and "no meaning vectors" in (result.reason or "")
    assert fake.embed_calls == []


async def test_a_cloud_query_without_consent_is_not_sent(
    indexed: None, store: SearchStore, search_settings: Settings
) -> None:
    cloud = FakeLLMBackend(id="router", kind="openrouter", is_local=False)
    settings = cloud_settings(search_settings, consent=False)
    searcher = Searcher(store, lambda: resolve(settings, ["ollama", "router"], lambda n: cloud))
    result = await searcher.query("certificate")
    assert cloud.embed_calls == []
    assert result.mode == "words" and "cloud service" in (result.reason or "")
    assert result.embedder == "cloud: openrouter"


async def test_only_stop_words(indexed: None, searcher: Searcher) -> None:
    result = await searcher.query("what did we discuss")
    assert result.mode == "meaning"  # nothing for the word index, meaning still searches
    empty = await searcher.query("   ")
    assert (empty.mode, empty.hits) == ("none", [])


# -- grouping and facts ----------------------------------------------------------------------


async def test_group_by_meeting_and_meeting_facts(indexed: None, searcher: Searcher) -> None:
    result = await searcher.query("Where did we spend more money than planned?", limit=40)
    groups = group_by_meeting(result.hits)
    assert [g.score for g in groups] == sorted((g.score for g in groups), reverse=True)
    assert all(len({h.mm3_id for h in g.hits}) == 1 for g in groups)
    facts = searcher.meeting_facts([g.mm3_id for g in groups], result.hits)
    finance = facts[str(by_key("finance").id)]
    assert finance.title == "Q3 Finance Review" and finance.date == "2026-09-02"
    assert finance.participants == ("Dana Whitfield", "Raj Patel", "Mei Lin")
    assert finance.speakers == ("Dana Whitfield", "Raj Patel")
    assert finance.note_path and finance.transcript_path
    assert set(finance.speakers_in_hits) <= set(finance.speakers)
    assert searcher.meeting_facts(["no-such-id"]) == {}


def test_passage_body_and_snippet() -> None:
    text = "Title · 2026-01-01\nTranscript\nSpeakers: Ann\nAnn: We went over budget again."
    body = passage_body(text)
    assert body == "Ann: We went over budget again."
    pieces = make_snippet(body, ["budgets"])
    assert ("budget", True) in pieces
    assert "".join(t for t, _ in pieces) == body


def test_model_prefixes() -> None:
    assert prefixes("nomic-embed-text:latest") == ("search_document: ", "search_query: ")
    assert prefixes("bge-m3") == ("", "")
    assert prefixes("intfloat/e5-large-v2")[1] == "query: "


async def test_query_uses_the_query_prefix(
    indexed: None, searcher: Searcher, fake: FakeLLMBackend
) -> None:
    fake.embed_calls.clear()
    await searcher.query("certificate")
    assert fake.embed_calls[0][1] == ("search_query: certificate",)
