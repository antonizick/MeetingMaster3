"""Everything a model drop-down needs, built on the server (ADR-0042).

One function turns a backend's model list into the grouped, priced, filtered picker data that both
New meeting and Settings show, so they cannot disagree: the capable models (``assess``), the
measured Best value / Best quality picks first, the rest cheapest first, the hidden count with a
reason for each, and an estimated cost for a meeting of the requested length.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from meetingmaster3.llm.base import LLMBackend, ModelInfo
from meetingmaster3.llm.cost import (
    DEFAULT_SECTIONS,
    estimate_cost,
    transcript_tokens_for,
)
from meetingmaster3.llm.pricing import BEDROCK_PRICING_URL, format_price, format_usd, is_stale
from meetingmaster3.llm.recommendations import Pick, load_picks
from meetingmaster3.templates.mapreduce import DetailLevel
from meetingmaster3.templates.model_check import assess, normalized_id, suggest

log = logging.getLogger(__name__)

DEFAULT_MINUTES = 60
PRICING_URLS = {
    "bedrock": BEDROCK_PRICING_URL,
    "openrouter": "https://openrouter.ai/models",
    "openai": "https://openai.com/api/pricing/",
}


@dataclass(frozen=True)
class MeetingShape:
    """What the cost estimate assumes about the meeting and its template."""

    minutes: float = DEFAULT_MINUTES
    sections: int = DEFAULT_SECTIONS
    detail: DetailLevel = "standard"


def _entry(
    model: ModelInfo,
    backend: LLMBackend,
    shape: MeetingShape,
    reason: str = "",
    pick: Pick | None = None,
) -> dict[str, Any]:
    priced = not backend.is_local and model.price_in is not None and model.price_out is not None
    estimate = None
    if priced:
        estimate = estimate_cost(
            model,
            transcript_tokens_for(shape.minutes),
            shape.sections,
            shape.detail,
            window=backend.context_window(model.id) or model.context_window,
        )
    name = model.name or model.id
    price_text = ""
    if priced and model.price_in is not None and model.price_out is not None:
        price_text = (
            "free"
            if model.price_in == 0 and model.price_out == 0
            else f"{format_price(model.price_in)} in / {format_price(model.price_out)} out "
            "per 1M tokens"
        )
    estimate_text = ""
    if estimate is not None:
        estimate_text = (
            f"about {format_usd(estimate)} for {round(shape.minutes)} minutes of meeting (estimate)"
        )
    parts = [
        name,
        f"{model.context_window:,}-token context" if model.context_window else "",
        price_text,
        estimate_text,
    ]
    return {
        "id": model.id,
        "name": name,
        "price_text": price_text,
        "summary": " · ".join(part for part in parts if part),
        "context_window": model.context_window,
        "price_in": model.price_in if priced else None,
        "price_out": model.price_out if priced else None,
        "price_source": model.price_source if priced else None,
        "price_as_of": model.price_as_of if priced else None,
        "free": model.free,
        "estimate_usd": estimate,
        "estimate_text": estimate_text,
        "badge": pick.badge if pick else None,
        "badge_label": pick.label if pick else None,
        "why": pick.why if pick else "",
        "measured": pick.measured if pick else "",
        "reason": reason,
        "usable": not reason,
        "can_generate": model.can_generate,
        "size_bytes": model.size_bytes,
    }


def _cost_key(entry: dict[str, Any]) -> tuple[int, float, str]:
    """Cheapest first by the meeting estimate; unpriced models after the priced ones."""
    cost = entry["estimate_usd"]
    return (0, cost, entry["name"].lower()) if cost is not None else (1, 0.0, entry["name"].lower())


def build_picker(
    backend: LLMBackend,
    models: Sequence[ModelInfo],
    max_context: int | None,
    shape: MeetingShape | None = None,
) -> dict[str, Any]:
    """Grouped picker data for ``models``. ``recommended`` and ``other`` hold the capable models,
    ``hidden`` the rest with a reason each. Local backends get no prices and no picks."""
    shape = shape or MeetingShape()
    picks = [] if backend.is_local else load_picks(backend.kind)
    recommended: list[dict[str, Any]] = []
    other: list[dict[str, Any]] = []
    hidden: list[dict[str, Any]] = []
    used: set[str] = set()
    for model in models:
        verdict = assess(model, backend, max_context)
        if not verdict.capable:
            hidden.append(_entry(model, backend, shape, reason=verdict.reason))
            continue
        pick = next(
            (
                p
                for p in picks
                if p.model.lower() == normalized_id(backend.kind, model.id) and p.badge not in used
            ),
            None,
        )
        if pick:
            used.add(pick.badge)
            recommended.append(_entry(model, backend, shape, pick=pick))
        else:
            other.append(_entry(model, backend, shape))
    recommended.sort(key=lambda e: list(dict.fromkeys(p.badge for p in picks)).index(e["badge"]))
    if backend.is_local:
        other.sort(key=lambda e: e["name"].lower())
    else:
        other.sort(key=_cost_key)
    hidden.sort(key=lambda e: e["name"].lower())
    table_dates = {e["price_as_of"] for e in (*recommended, *other) if e["price_source"] == "table"}
    as_of = min(table_dates) if table_dates else None
    return {
        "backend_kind": backend.kind,
        "is_local": backend.is_local,
        "suggested": suggest(models, backend, max_context),
        "recommended": recommended,
        "other": other,
        "hidden": hidden,
        "hidden_count": len(hidden),
        "has_prices": any(e["estimate_usd"] is not None for e in (*recommended, *other)),
        "prices_as_of": as_of,
        "prices_stale": bool(as_of) and is_stale(as_of),
        "pricing_url": PRICING_URLS.get(backend.kind, ""),
        "minutes": shape.minutes,
    }


def meeting_shape(minutes: float | None, template_id: str | None) -> MeetingShape:
    """The estimate's assumptions: ``minutes`` of audio (default one hour) and the section count
    and detail of the chosen built-in template (a custom template is estimated like Default
    Notes)."""
    from meetingmaster3.templates.loader import load_builtin

    length = minutes if minutes and minutes > 0 else DEFAULT_MINUTES
    if template_id:
        try:
            template = load_builtin(template_id)
        except Exception:  # unknown or custom template id: fall back to the default shape
            log.debug("No built-in template %r for the cost estimate", template_id)
        else:
            return MeetingShape(length, len(template.sections), template.params.detail)
    return MeetingShape(length)
