"""Model prices for the cloud pickers (ADR-0042).

OpenRouter reports its own prices in the model list, so they are live. AWS Bedrock does not, so
``bedrock_models.yaml`` carries a small dated table (on-demand USD per 1M tokens by model-id
prefix) shown with its ``as_of`` date. Prices are informational: nothing here blocks a job.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import functools
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml

from meetingmaster3.llm.base import ModelInfo

MODELS_FILE = Path(__file__).with_name("bedrock_models.yaml")
STALE_AFTER_DAYS = 180
"""A table price older than this is shown with a "may be out of date" note."""
BEDROCK_PRICING_URL = "https://aws.amazon.com/bedrock/pricing/"


@dataclass(frozen=True)
class PriceTable:
    as_of: str
    prices: Mapping[str, tuple[float, float]]
    """Model-id prefix -> (USD per 1M input tokens, USD per 1M output tokens)."""


@functools.cache
def bedrock_table(path: Path = MODELS_FILE) -> PriceTable:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    prices = {
        str(k): (float(v["in"]), float(v["out"])) for k, v in (data.get("prices") or {}).items()
    }
    return PriceTable(str(data.get("prices_as_of", "")), prices)


def bedrock_price(model: str, table: PriceTable | None = None) -> tuple[float, float] | None:
    """The table price of ``model``'s family (longest prefix wins; geography prefixes such as
    ``us.`` are ignored), or None when the table does not list it."""
    from meetingmaster3.llm.bedrock import base_model_id  # local: bedrock imports this module

    table = table or bedrock_table()
    model_id = base_model_id(model).lower()
    matches = [p for p in table.prices if model_id.startswith(p.lower())]
    return table.prices[max(matches, key=len)] if matches else None


def is_stale(as_of: str | None, today: dt.date | None = None) -> bool:
    """True when ``as_of`` (an ISO date) is missing, unreadable or older than the limit."""
    try:
        when = dt.date.fromisoformat(as_of or "")
    except ValueError:
        return True
    return ((today or dt.date.today()) - when).days > STALE_AFTER_DAYS


def with_table_price(model: ModelInfo, table: PriceTable | None = None) -> ModelInfo:
    """``model`` with its Bedrock table price filled in, if the table lists the family."""
    table = table or bedrock_table()
    found = bedrock_price(model.id, table)
    if found is None:
        return model
    return dataclasses.replace(
        model,
        price_in=found[0],
        price_out=found[1],
        price_source="table",
        price_as_of=table.as_of,
    )


def cost_usd(model: ModelInfo, input_tokens: int, output_tokens: int) -> float | None:
    """The price of a call with these token counts, or None when the model has no price."""
    if model.price_in is None or model.price_out is None:
        return None
    return (input_tokens * model.price_in + output_tokens * model.price_out) / 1_000_000


def format_usd(amount: float) -> str:
    """Money for a small estimate: ``$0.003``, ``$0.017``, ``$0.07``, ``$1.20``."""
    if amount < 0.0005:
        return "less than $0.001"
    if amount < 0.1:
        text = f"{amount:.3f}"
        return "$" + (text[:-1] if text.endswith("0") else text)
    return f"${amount:.2f}"


def format_price(per_million: float) -> str:
    """A per-1M-token price without noise: ``$0.10``, ``$2.00``, ``$0.035``; ``free`` for zero."""
    if per_million == 0:
        return "free"
    text = f"{per_million:.4f}".rstrip("0")
    whole, _, frac = text.partition(".")
    return f"${whole}.{frac.ljust(2, '0')}"
