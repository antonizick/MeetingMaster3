"""Context budgeting (spec R6): token estimates, fit checks and speaker-turn chunking."""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass

from meetingmaster3.llm.base import LLMBackend

CHARS_PER_TOKEN = 4
BUDGET_FRACTION = 0.7
DEFAULT_CONTEXT_WINDOW = 8192  # used when a backend cannot tell us; deliberately conservative
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def estimate_tokens(text: str) -> int:
    """Rough token count (about four characters per token)."""
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def usable_tokens(window: int) -> int:
    """The share of a context window a prompt may fill before we switch to map-reduce."""
    return int(window * BUDGET_FRACTION)


async def window_for(backend: LLMBackend, model: str) -> int:
    """The model's context window, asking the backend once and falling back to a safe default."""
    window = backend.context_window(model)
    if window is None:
        await backend.warm(model)
        window = backend.context_window(model)
    return window or DEFAULT_CONTEXT_WINDOW


def fits_window(window: int, prompt: str, reserve_output: int = 0) -> bool:
    return estimate_tokens(prompt) + reserve_output <= usable_tokens(window)


async def fits(backend: LLMBackend, model: str, prompt: str, reserve_output: int = 0) -> bool:
    """True when ``prompt`` plus the expected output stays within 70% of ``model``'s window."""
    return fits_window(await window_for(backend, model), prompt, reserve_output)


@dataclass(frozen=True)
class Turn:
    """One speaker turn. Phase 09 builds these from the transcript segments."""

    speaker: str
    text: str
    start: float | None = None
    continued: bool = False  # True for the later pieces of a turn that had to be split

    def render(self) -> str:
        return f"{self.speaker}: {self.text}"

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.render())


@dataclass(frozen=True)
class Chunk:
    index: int
    turns: tuple[Turn, ...]
    overlap: int  # the first ``overlap`` turns repeat the end of the previous chunk

    @property
    def new_turns(self) -> tuple[Turn, ...]:
        return self.turns[self.overlap :]

    @property
    def tokens(self) -> int:
        return sum(t.tokens for t in self.turns)

    def render(self) -> str:
        return "\n".join(t.render() for t in self.turns)


def _split_long(turn: Turn, max_tokens: int) -> list[Turn]:
    """Split a turn that alone exceeds the budget, at sentence ends where possible."""
    if turn.tokens <= max_tokens:
        return [turn]
    room = max(1, (max_tokens - estimate_tokens(f"{turn.speaker}: ")) * CHARS_PER_TOKEN)
    pieces: list[str] = []
    current = ""
    for sentence in _SENTENCE_END.split(turn.text):
        while len(sentence) > room:  # no sentence break to use: hard split
            if current:
                pieces.append(current)
                current = ""
            pieces.append(sentence[:room])
            sentence = sentence[room:]
        if current and len(current) + 1 + len(sentence) > room:
            pieces.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current)
    return [
        Turn(turn.speaker, piece, turn.start if i == 0 else None, continued=i > 0)
        for i, piece in enumerate(pieces)
    ]


def chunk_transcript(
    turns: Sequence[Turn], max_tokens: int, overlap_turns: int = 1, per_turn: int = 0
) -> list[Chunk]:
    """Group turns into chunks of at most ``max_tokens`` estimated tokens, counting ``per_turn``
    more for each turn (what the caller adds when it renders one, such as a timestamp).

    Chunks break only between turns, so a turn is never cut in two unless it alone exceeds the
    budget (it is then split at sentence ends and the pieces are marked ``continued``). Each
    chunk after the first starts with up to ``overlap_turns`` turns repeated from the previous
    one for context; the overlap is dropped when it would not leave room for new content.
    Every input turn appears in exactly one chunk's ``new_turns``.
    """
    if max_tokens < 1:
        raise ValueError("max_tokens must be positive")

    def cost(group: Sequence[Turn]) -> int:
        return sum(t.tokens + per_turn for t in group)

    pieces = [p for t in turns for p in _split_long(t, max(1, max_tokens - per_turn))]
    chunks: list[Chunk] = []
    current: list[Turn] = []
    overlap = 0
    new_count = 0
    for piece in pieces:
        if new_count and cost(current) + cost([piece]) > max_tokens:
            chunks.append(Chunk(len(chunks), tuple(current), overlap))
            carry = current[-overlap_turns:] if overlap_turns > 0 else []
            while carry and cost(carry) + cost([piece]) > max_tokens:
                carry = carry[1:]
            current, overlap, new_count = list(carry), len(carry), 0
        current.append(piece)
        new_count += 1
    if new_count:
        chunks.append(Chunk(len(chunks), tuple(current), overlap))
    return chunks
