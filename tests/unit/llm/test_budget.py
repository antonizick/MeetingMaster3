from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from meetingmaster3.llm.base import ConnectionStatus, GenerateRequest, GenerateResult
from meetingmaster3.llm.budget import (
    DEFAULT_CONTEXT_WINDOW,
    Turn,
    chunk_transcript,
    estimate_tokens,
    fits,
    fits_window,
    usable_tokens,
    window_for,
)

turns_st = st.lists(
    st.builds(
        Turn,
        speaker=st.sampled_from(["Alice", "Bob", "Carol"]),
        text=st.text(alphabet="abcdefg .!?", min_size=1, max_size=600).filter(str.strip),
    ),
    max_size=40,
)


def test_estimate_and_window_math() -> None:
    assert (
        estimate_tokens("") == 0 and estimate_tokens("abcd") == 1 and estimate_tokens("abcde") == 2
    )
    assert usable_tokens(10_000) == 7_000
    assert fits_window(1000, "x" * 2800) and not fits_window(1000, "x" * 2804)
    assert not fits_window(1000, "x" * 2000, reserve_output=300)


@given(turns_st, st.integers(min_value=20, max_value=300), st.integers(min_value=0, max_value=3))
def test_chunks_cover_every_turn_once_within_budget(
    turns: list[Turn], max_tokens: int, overlap: int
) -> None:
    chunks = chunk_transcript(turns, max_tokens, overlap)
    assert all(c.tokens <= max_tokens for c in chunks)
    rebuilt = [t for c in chunks for t in c.new_turns]
    # splitting only happens for oversize turns, and pieces rejoin to the original text
    merged: list[Turn] = []
    for t in rebuilt:
        if t.continued and merged:
            merged[-1] = Turn(merged[-1].speaker, merged[-1].text + " " + t.text)
        else:
            merged.append(t)
    assert [(m.speaker, "".join(m.text.split())) for m in merged] == [
        (t.speaker, "".join(t.text.split())) for t in turns
    ]


@given(turns_st, st.integers(min_value=20, max_value=300))
def test_turns_within_budget_are_never_split(turns: list[Turn], max_tokens: int) -> None:
    chunks = chunk_transcript(turns, max_tokens)
    produced = [t for c in chunks for t in c.new_turns]
    expected = sum(1 for t in turns if t.tokens <= max_tokens)
    assert sum(1 for t in produced if not t.continued and t.tokens <= max_tokens) >= expected


def test_overlap_repeats_previous_tail() -> None:
    turns = [Turn("A", "x" * 40), Turn("B", "y" * 40), Turn("A", "z" * 40)]  # 11 tokens each
    chunks = chunk_transcript(turns, max_tokens=25, overlap_turns=1)
    assert [len(c.turns) for c in chunks] == [2, 2]
    assert chunks[1].turns[0].text == "y" * 40 and chunks[1].overlap == 1
    assert [t.text[0] for t in chunks[1].new_turns] == ["z"]


def test_overlap_dropped_when_it_leaves_no_room() -> None:
    turns = [Turn("A", "x" * 40), Turn("B", "y" * 40)]
    chunks = chunk_transcript(turns, max_tokens=15, overlap_turns=1)
    assert [c.overlap for c in chunks] == [0, 0] and all(c.tokens <= 15 for c in chunks)


def test_no_chunking_when_everything_fits() -> None:
    chunks = chunk_transcript([Turn("A", "hello"), Turn("B", "there")], max_tokens=1000)
    assert len(chunks) == 1 and chunks[0].overlap == 0
    assert chunks[0].render() == "A: hello\nB: there"


def test_empty_transcript() -> None:
    assert chunk_transcript([], 100) == []


class _Fake:
    id, kind, is_local = "f", "fake", True

    def __init__(self, window: int | None) -> None:
        self._w, self.warmed = window, False

    def context_window(self, model: str) -> int | None:
        return self._w

    async def warm(self, model: str) -> None:
        self.warmed = True

    async def generate(self, req: GenerateRequest) -> GenerateResult: ...
    async def list_models(self) -> list: ...
    async def test_connection(self) -> ConnectionStatus: ...
    def stream(self, req: GenerateRequest): ...


async def test_window_for_falls_back_and_fits_uses_it() -> None:
    unknown = _Fake(None)
    assert await window_for(unknown, "m") == DEFAULT_CONTEXT_WINDOW and unknown.warmed
    assert await fits(_Fake(1000), "m", "x" * 2000)
    assert not await fits(_Fake(1000), "m", "x" * 3000)
