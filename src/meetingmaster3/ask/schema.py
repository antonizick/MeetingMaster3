"""What the model returns at each step of the Ask-AI agent, validated (pure; no I/O).

The agent never trusts the shape of a reply: each one is parsed with the same tolerant JSON
reading as map-reduce (fences, reasoning blocks, trailing commas, a cut-off object closed), then
validated and normalised here. Anything that does not fit is an :class:`AskParseError`, which the
pipeline answers with one repair request and then a safe fallback.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from meetingmaster3.templates.mapreduce import json_candidates

MAX_QUERIES = 6
MAX_QUERY_CHARS = 200
MAX_PEOPLE = 12
MAX_QUOTES = 3
MAX_FINDING_CHARS = 600
MAX_FIELD_CHARS = 300
Want = Literal["count", "people", "table", "timeline", "summary"]
WANTS: tuple[Want, ...] = ("count", "people", "table", "timeline", "summary")
Relevance = Literal["yes", "partly", "no"]
_TIME_RE = re.compile(r"^(?:(\d{1,2}):)?(\d{1,2}):([0-5]\d)$")


class AskParseError(ValueError):
    """A reply that is not the JSON object asked for (the message says what was wrong)."""


def _clip(value: Any, limit: int = MAX_FIELD_CHARS) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit].rstrip()


def _strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(v) for v in value if isinstance(v, str | int | float) and str(v).strip()]
    return []


def _iso_date(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return dt.date.fromisoformat(value.strip()[:10]).isoformat()
    except ValueError:
        return None


class Plan(BaseModel):
    """Step 1: how to search for the question."""

    queries: list[str] = Field(default_factory=list)
    date_from: str | None = None
    date_to: str | None = None
    people: list[str] = Field(default_factory=list)
    wants: list[Want] = Field(default_factory=list)
    topic: str = ""

    @field_validator("queries", mode="before")
    @classmethod
    def _queries(cls, v: Any) -> list[str]:
        out: list[str] = []
        for q in _strings(v):
            q = _clip(q, MAX_QUERY_CHARS)
            if q and q.casefold() not in {o.casefold() for o in out}:
                out.append(q)
        if not out:
            raise ValueError("no search queries")
        return out[:MAX_QUERIES]

    @field_validator("date_from", "date_to", mode="before")
    @classmethod
    def _date(cls, v: Any) -> str | None:
        return _iso_date(v)

    @field_validator("people", mode="before")
    @classmethod
    def _people(cls, v: Any) -> list[str]:
        return [p for p in (_clip(x, 80) for x in _strings(v)) if p][:MAX_PEOPLE]

    @field_validator("wants", mode="before")
    @classmethod
    def _wants(cls, v: Any) -> list[str]:
        words = [w.strip().lower() for w in _strings(v)]
        return [w for w in WANTS if w in words]

    @field_validator("topic", mode="before")
    @classmethod
    def _topic(cls, v: Any) -> str:
        return _clip(v, MAX_QUERY_CHARS)


class PersonFinding(BaseModel):
    name: str
    role: str = ""
    contribution: str = ""

    @field_validator("name", mode="before")
    @classmethod
    def _name(cls, v: Any) -> str:
        name = _clip(v, 80)
        if not name:
            raise ValueError("a person without a name")
        return name

    @field_validator("role", "contribution", mode="before")
    @classmethod
    def _text(cls, v: Any) -> str:
        return _clip(v)


class Quote(BaseModel):
    text: str
    time: str | None = None

    @field_validator("text", mode="before")
    @classmethod
    def _text(cls, v: Any) -> str:
        text = _clip(v).strip("\"'“”")
        if not text:
            raise ValueError("an empty quote")
        return text

    @field_validator("time", mode="before")
    @classmethod
    def _time(cls, v: Any) -> str | None:
        text = str(v or "").strip().strip("[]")
        return text if _TIME_RE.match(text) else None


class Reading(BaseModel):
    """Step 3: what one meeting says about the question."""

    relevant: Relevance
    finding: str = ""
    people: list[PersonFinding] = Field(default_factory=list)
    quotes: list[Quote] = Field(default_factory=list)

    @field_validator("relevant", mode="before")
    @classmethod
    def _relevant(cls, v: Any) -> str:
        if isinstance(v, bool):
            return "yes" if v else "no"
        word = str(v or "").strip().lower()
        if word in {"yes", "true", "relevant", "y"}:
            return "yes"
        if word in {"partly", "partial", "partially", "somewhat", "some"}:
            return "partly"
        if word in {"no", "false", "none", "irrelevant", "n"}:
            return "no"
        raise ValueError("relevant must be yes, partly or no")

    @field_validator("finding", mode="before")
    @classmethod
    def _finding(cls, v: Any) -> str:
        return _clip(v, MAX_FINDING_CHARS)

    @field_validator("people", mode="before")
    @classmethod
    def _people(cls, v: Any) -> list[Any]:
        items = v if isinstance(v, list) else []
        out: list[Any] = []
        for item in items:
            if isinstance(item, str):
                item = {"name": item}
            if isinstance(item, dict) and _clip(item.get("name"), 80):
                out.append(item)
        return out[:MAX_PEOPLE]

    @field_validator("quotes", mode="before")
    @classmethod
    def _quotes(cls, v: Any) -> list[Any]:
        items = v if isinstance(v, list) else []
        out: list[Any] = []
        for item in items:
            if isinstance(item, str):
                item = {"text": item}
            if isinstance(item, dict) and _clip(item.get("text")):
                out.append(item)
        return out[:MAX_QUOTES]


def parse_reply[T: BaseModel](text: str, model: type[T]) -> T:
    """The first JSON object in ``text`` that validates as ``model``."""
    last = "no JSON object found"
    for candidate in json_candidates(text):
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError as exc:
            last = f"invalid JSON: {exc.msg} at line {exc.lineno}"
            continue
        if not isinstance(data, dict):
            last = "the reply is not a JSON object"
            continue
        try:
            return model.model_validate(data)
        except ValidationError as exc:
            first = exc.errors()[0]
            where = ".".join(str(p) for p in first.get("loc", ())) or "the object"
            last = f"wrong shape at {where}: {first.get('msg')}"
    raise AskParseError(last)
