"""Estimate the tokens, and so the price, of writing one meeting's notes (ADR-0042).

The numbers are measured, not guessed: Phase 15g's live runs (``tests/eval/cloud-results.md``)
gave about 18 700 input and 2 500-3 000 output tokens for a note on the synthetic meetings, and
about 80 000 input tokens for a 31-minute real meeting with Default Notes (8 sections). Those two
facts fit a model of one call per section that re-sends the transcript: ``sections x (transcript +
prompt overhead)`` in, ``sections x ~350`` out. A meeting too long for the model's window is
summarised in parts (map-reduce), which sends the transcript once and then only short notes.
The result is an estimate; it is always shown as one.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from meetingmaster3.llm.base import ModelInfo
from meetingmaster3.llm.budget import DEFAULT_CONTEXT_WINDOW, usable_tokens
from meetingmaster3.llm.pricing import cost_usd
from meetingmaster3.templates.generator import (
    NOTES_DENSITY,
    extraction_max_tokens,
    map_budget,
    window_is_workable,
)
from meetingmaster3.templates.mapreduce import DetailLevel

TRANSCRIPT_TOKENS_PER_MINUTE = 300
"""Prompt tokens one minute of meeting adds (speech, speaker names, timestamps). Measured: a
31-minute real meeting sent 80 000 input tokens through Default Notes' 8 section calls."""
PROMPT_OVERHEAD_TOKENS = 700
"""Template and system instructions each call carries besides the transcript."""
OUTPUT_TOKENS_PER_SECTION = 350
"""Mean output per section call (2 500-3 000 tokens over Default Notes' 8 sections)."""
MAP_NOTES_SHARE = 0.6
"""Share of a map call's output allowance a real extraction uses."""
DEFAULT_SECTIONS = 8
MEASURED_ON = "2026-10-15"
SOURCE = "Phase 15g live runs, tests/eval/cloud-results.md"


@dataclass(frozen=True)
class TokenEstimate:
    input_tokens: int
    output_tokens: int
    calls: int
    map_reduce: bool


def transcript_tokens_for(minutes: float) -> int:
    return round(max(minutes, 0.0) * TRANSCRIPT_TOKENS_PER_MINUTE)


def estimate_tokens_for_note(
    transcript_tokens: int,
    window: int | None,
    sections: int = DEFAULT_SECTIONS,
    detail: DetailLevel = "standard",
    section_max_tokens: int | None = None,
) -> TokenEstimate:
    """Tokens one note costs. ``window`` is the model's context window (None: the generator's
    safe default). Uses the generator's own budget functions to decide between one call per
    section and map-reduce."""
    window = window or DEFAULT_CONTEXT_WINDOW
    sections = max(sections, 1)
    per_section_out = min(OUTPUT_TOKENS_PER_SECTION, section_max_tokens or 10**9)
    full_call = transcript_tokens + PROMPT_OVERHEAD_TOKENS + per_section_out
    if full_call <= usable_tokens(window) or not window_is_workable(window):
        return TokenEstimate(
            input_tokens=sections * (transcript_tokens + PROMPT_OVERHEAD_TOKENS),
            output_tokens=sections * per_section_out,
            calls=sections,
            map_reduce=False,
        )
    chunk = max(map_budget(window, detail), 1)
    parts = math.ceil(transcript_tokens / chunk)
    map_out = round(extraction_max_tokens(detail) * MAP_NOTES_SHARE)
    notes = round(parts * map_out * NOTES_DENSITY)
    return TokenEstimate(
        input_tokens=transcript_tokens
        + parts * PROMPT_OVERHEAD_TOKENS
        + sections * (notes + PROMPT_OVERHEAD_TOKENS),
        output_tokens=parts * map_out + sections * per_section_out,
        calls=parts + sections,
        map_reduce=True,
    )


def estimate_cost(
    model: ModelInfo,
    transcript_tokens: int,
    sections: int = DEFAULT_SECTIONS,
    detail: DetailLevel = "standard",
    section_max_tokens: int | None = None,
    window: int | None = None,
) -> float | None:
    """Estimated USD for one note with ``model``, or None when it has no price."""
    est = estimate_tokens_for_note(
        transcript_tokens, window or model.context_window, sections, detail, section_max_tokens
    )
    return cost_usd(model, est.input_tokens, est.output_tokens)
