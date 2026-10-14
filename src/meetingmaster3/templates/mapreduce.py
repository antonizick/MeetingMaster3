"""Map-reduce for long meetings (R6, ADR-0016): per-chunk JSON extraction, repair, merge.

The map step asks the model for a :class:`ChunkExtraction` per transcript chunk. Small local
models often wrap JSON in prose or code fences or leave trailing commas, so :func:`parse_extraction`
repairs what it safely can; the generator asks once more with the parser error before giving up
on a chunk. :func:`merge` concatenates the chunks in time order and removes near-duplicates
(the overlap turn between chunks makes models restate the same item). :func:`render_notes`
turns the merged result into the compact text the sections are generated from.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from meetingmaster3.llm.budget import estimate_tokens

EXTRACTION_SYSTEM = """\
You extract structured notes from one part of a meeting transcript. Use only what this part \
says. Never invent people, owners, dates or numbers. Use speaker names exactly as given. Reply \
with one JSON object and nothing else."""

EXTRACTION_SCHEMA = """\
{
  "summary": "2-4 sentences: what this part of the meeting covered and concluded",
  "decisions": [
    {"text": "a decision that was actually made", "rationale": "reason given, or empty",
     "by": "Name, or empty", "time": "mm:ss"}],
  "actions": [
    {"task": "what will be done, starting with a verb", "owner": "Name, or Unassigned",
     "due": "deadline as stated, or not stated", "time": "mm:ss"}],
  "questions": [
    {"text": "a question or issue left unresolved", "raised_by": "Name, or empty",
     "time": "mm:ss"}],
  "points": [
    {"text": "a substantive fact, update, figure or position, in your own words",
     "speaker": "Name", "time": "mm:ss"}]
}"""
MAX_POINTS = 10


DetailLevel = Literal["standard", "high"]

HIGH_DETAIL_POINTS = 30
HIGH_DETAIL_EXCHANGES = 10
HIGH_DETAIL_SCHEMA = """\
{
  "summary": "3-5 sentences: what this part of the meeting covered and concluded",
  "decisions": [
    {"text": "a decision that was actually made", "rationale": "reason given, or empty",
     "by": "Name, or empty", "time": "mm:ss"}],
  "actions": [
    {"task": "what someone committed to do, starting with a verb", "owner": "Name, or Unassigned",
     "due": "deadline as stated, or not stated", "time": "mm:ss"}],
  "questions": [
    {"text": "a question or issue left unresolved", "raised_by": "Name, or empty",
     "time": "mm:ss"}],
  "points": [
    {"topic": "the subject in 2-5 words, the same label for points on the same subject",
     "text": "a substantive fact, update, figure or position, with its specifics",
     "speaker": "Name", "time": "mm:ss"}],
  "exchanges": [
    {"asked_by": "Name", "question": "the question in a few words",
     "answered_by": "Name", "answer": "the answer with its specifics", "time": "mm:ss"}]
}"""
"""``params.detail: high`` (ADR-0039): points carry a topic label and keep their specifics, there
are up to :data:`HIGH_DETAIL_POINTS` of them per part, and answered questions are kept as
``exchanges`` with who asked and who answered."""


def max_points(detail: DetailLevel = "standard") -> int:
    return HIGH_DETAIL_POINTS if detail == "high" else MAX_POINTS


def extraction_prompt(
    part: int,
    parts: int,
    transcript_text: str,
    cues: Sequence[str] = (),
    *,
    detail: DetailLevel = "standard",
    relevant_tasks: bool = False,
) -> str:
    """``relevant_tasks`` (``params.task_candidates: relevant``, ADR-0039) keeps small talk that
    only sounds like a commitment out of the action items."""
    commitment = (
        "a commitment to real work for the meeting is an action item (owner: the speaker), "
        "small talk and personal remarks are not"
        if relevant_tasks
        else "each commitment is an action item (owner: the speaker)"
    )
    candidates = (
        "These sentences in this part sound like commitments, requests or suggestions; "
        + commitment
        + ", a suggestion nobody took on is an action with owner Unassigned:\n<candidates>\n"
        + "\n".join(cues)
        + "\n</candidates>\n\n"
        if cues
        else ""
    )
    if detail == "high":
        schema = HIGH_DETAIL_SCHEMA
        points = (
            f"For points, record every substantive point, up to {HIGH_DETAIL_POINTS}, in the "
            "order they were made, each in one sentence of at most 40 words. Keep the "
            "specifics: numbers and quantities, names of products, tools, vendors, teams and "
            "organisations, dates and deadlines, changes in roles or structure, and reasons "
            "given. Give each point the person who said it: when someone answers another "
            "person's question, the answer's points belong to the person who answered. "
            f"Also list up to {HIGH_DETAIL_EXCHANGES} substantive questions that were answered "
            "in 'exchanges', each with who asked, who answered and the answer in at most 40 "
            "words. Action items are only what someone committed to do or was asked to do and "
            "agreed: steps someone describes when answering a question or a hypothetical "
            "scenario ('I would reset the password') and practices already in place are "
            "points, not action items. Keep the other texts short."
        )
    else:
        schema = EXTRACTION_SCHEMA
        points = (
            f"For points, keep only the {MAX_POINTS} most important ones, each at most 20 words "
            "in your own words (do not copy sentences). Keep every text short."
        )
    return (
        f"This is part {part} of {parts} of a meeting transcript"
        + (" (the first line repeats the end of the previous part for context)" if part > 1 else "")
        + f".\n\n<transcript>\n{transcript_text}\n</transcript>\n\n"
        + candidates
        + "Extract the notes as JSON with exactly this shape (use empty lists when there is "
        f"nothing; times come from the transcript):\n{schema}\n\n"
        "Include every decision, action item and open question. "
        + points
        + " Reply with the JSON object only."
    )


def repair_prompt(error: str, *, truncated: bool = False, detail: DetailLevel = "standard") -> str:
    if truncated:
        limit = max_points(detail) // 2
        return (
            "Your reply was cut off because it was too long. Reply again with the same JSON "
            f"shape but much shorter: at most {limit} points, every text under "
            f"{25 if detail == 'high' else 15} words, and nothing before or after the object."
        )
    return (
        f"Your reply could not be parsed as the requested JSON ({error}). Reply again with only "
        "the JSON object, with the same keys, and nothing before or after it."
    )


class _Item(BaseModel):
    model_config = ConfigDict(extra="ignore", coerce_numbers_to_str=True)

    @field_validator("*", mode="before")
    @classmethod
    def _text(cls, v: Any) -> Any:
        if v is None:
            return ""
        if isinstance(v, list):
            return ", ".join(str(x) for x in v)
        return v


class Point(_Item):
    text: str
    speaker: str = ""
    time: str = ""
    topic: str = ""
    """Only asked for with ``detail: high``."""


class Decision(_Item):
    text: str
    rationale: str = ""
    by: str = ""
    time: str = ""


class Action(_Item):
    task: str
    owner: str = ""
    due: str = ""
    time: str = ""


class Question(_Item):
    text: str
    raised_by: str = ""
    time: str = ""


def _items(v: Any) -> Any:
    if v is None:
        return []
    if isinstance(v, dict):
        return [v]
    if isinstance(v, list):
        return [{"text": x} if isinstance(x, str) else x for x in v if x]
    return v


class Exchange(_Item):
    question: str
    asked_by: str = ""
    answer: str = ""
    answered_by: str = ""
    time: str = ""


class ChunkExtraction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    summary: str = ""
    points: list[Point] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)
    actions: list[Action] = Field(default_factory=list)
    questions: list[Question] = Field(default_factory=list)
    exchanges: list[Exchange] = Field(default_factory=list)
    """Only asked for with ``detail: high``."""

    @field_validator("points", "decisions", "questions", "actions", "exchanges", mode="before")
    @classmethod
    def _lists(cls, v: Any) -> Any:
        return _items(v)

    @field_validator("actions", mode="before")
    @classmethod
    def _actions(cls, v: Any) -> Any:
        return [
            {**x, "task": x.get("task") or x.get("text") or x.get("action", "")}
            if isinstance(x, dict)
            else x
            for x in (v or [])
        ]

    @field_validator("summary", mode="before")
    @classmethod
    def _summary(cls, v: Any) -> Any:
        if v is None:
            return ""
        if isinstance(v, list):
            return " ".join(str(x) for x in v)
        return v


class ExtractionError(ValueError):
    pass


_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*\n?(.*?)```", re.S)
_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")
_THINK_RE = re.compile(r"<(think|thinking|reasoning)>.*?</\1>", re.S | re.I)


def _candidates(text: str) -> list[str]:
    text = _THINK_RE.sub("", text).strip()
    out = [text]
    out += [m.group(1).strip() for m in _FENCE_RE.finditer(text)]
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        out.append(text[start : end + 1])
    salvaged = close_truncated(text)
    if salvaged is not None:
        out.append(salvaged)
    return out


def close_truncated(text: str, max_tries: int = 60) -> str | None:
    """Salvage a JSON object cut off by the output limit: drop the unfinished tail after the
    last complete ``}``/``]`` and close the open brackets. ``None`` if nothing parses."""
    start = text.find("{")
    if start == -1:
        return None
    body = text[start:]
    cuts = [i + 1 for i, ch in enumerate(body) if ch in "}]"]
    for cut in reversed(cuts[-max_tries:]):
        piece = body[:cut]
        stack: list[str] = []
        in_string = escaped = False
        for ch in piece:
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
            elif ch == '"':
                in_string = True
            elif ch in "{[":
                stack.append("}" if ch == "{" else "]")
            elif ch in "}]" and stack:
                stack.pop()
        if in_string:
            continue
        candidate = piece.rstrip().rstrip(",") + "".join(reversed(stack))
        try:
            json.loads(candidate)
        except json.JSONDecodeError:
            continue
        return candidate
    return None


def parse_extraction(text: str) -> ChunkExtraction:
    """Parse (and safely repair) one map answer. Raises :class:`ExtractionError`."""
    last = "no JSON object found"
    for candidate in _candidates(text):
        for attempt in (candidate, _TRAILING_COMMA_RE.sub(r"\1", candidate)):
            try:
                data = json.loads(attempt)
            except json.JSONDecodeError as exc:
                last = f"invalid JSON: {exc.msg} at line {exc.lineno}"
                continue
            if not isinstance(data, dict):
                last = "the reply is not a JSON object"
                continue
            try:
                return ChunkExtraction.model_validate(data)
            except ValidationError as exc:
                first = exc.errors()[0]
                where = ".".join(str(p) for p in first.get("loc", ()))
                last = f"wrong shape at {where}: {first.get('msg')}"
    raise ExtractionError(last)


# -- merge ------------------------------------------------------------------------------------

_NORM_RE = re.compile(r"[^\w\s]")


def _norm(text: str) -> str:
    return " ".join(_NORM_RE.sub(" ", text.casefold()).split())


def _similar(a: str, b: str) -> bool:
    """Same item restated: equal after normalisation, or one contains the other, or most
    words are shared."""
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return na == nb
    if na == nb or (min(len(na), len(nb)) >= 12 and (na in nb or nb in na)):
        return True
    wa, wb = set(na.split()), set(nb.split())
    if min(len(wa), len(wb)) < 4:
        return False
    return len(wa & wb) / min(len(wa), len(wb)) >= 0.8


_PLACEHOLDERS = frozenset({"unassigned", "not stated"})


def _combine[T: BaseModel](old: T, new: T, key: str) -> T:
    """One item from two restatements: the wording of the clearly more detailed one, the
    earliest timestamp, and any field (owner, due date...) that only one of them has. A named
    owner beats "Unassigned"."""
    longer = len(str(getattr(new, key))) >= 1.2 * len(str(getattr(old, key)))
    base, other = (new, old) if longer else (old, new)
    data = base.model_dump()
    for field_name, value in other.model_dump().items():
        current = str(data.get(field_name) or "")
        empty = not current or _norm(current) in _PLACEHOLDERS
        if empty and value and _norm(str(value)) not in _PLACEHOLDERS:
            data[field_name] = value
    if getattr(old, "time", ""):
        data["time"] = old.time  # type: ignore[attr-defined]
    return type(old).model_validate(data)


def _dedupe[T: BaseModel](items: list[T], key: str, owner_key: str | None = None) -> list[T]:
    kept: list[T] = []
    for item in items:
        text = str(getattr(item, key))
        if not text.strip():
            continue
        for i, other in enumerate(kept):
            if owner_key is not None:
                o1, o2 = _norm(str(getattr(item, owner_key))), _norm(str(getattr(other, owner_key)))
                if o1 and o2 and o1 != o2 and "unassigned" not in (o1, o2):
                    continue  # the same task for two different people
            if _similar(text, str(getattr(other, key))):
                kept[i] = _combine(other, item, key)
                break
        else:
            kept.append(item)
    return kept


class MergedNotes(BaseModel):
    summaries: list[tuple[str, str]] = Field(default_factory=list)
    """(time range, summary) per chunk."""
    points: list[Point] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)
    actions: list[Action] = Field(default_factory=list)
    questions: list[Question] = Field(default_factory=list)
    exchanges: list[Exchange] = Field(default_factory=list)
    skipped_chunks: list[int] = Field(default_factory=list)


def merge(chunks: list[ChunkExtraction | None], ranges: list[str] | None = None) -> MergedNotes:
    """Concatenate chunk extractions in order and remove near-duplicates. ``None`` marks a chunk
    whose extraction failed."""
    out = MergedNotes()
    for i, c in enumerate(chunks):
        if c is None:
            out.skipped_chunks.append(i)
            continue
        if c.summary.strip():
            out.summaries.append((ranges[i] if ranges else f"part {i + 1}", c.summary.strip()))
        out.points += c.points
        out.decisions += c.decisions
        out.actions += c.actions
        out.questions += c.questions
        out.exchanges += c.exchanges
    out.points = _dedupe(out.points, "text")
    out.decisions = _dedupe(out.decisions, "text")
    out.actions = _dedupe(out.actions, "task", owner_key="owner")
    out.questions = _dedupe(out.questions, "text")
    out.exchanges = _dedupe(out.exchanges, "question")
    return out


def _t(time: str) -> str:
    return f"[{time.strip().strip('[]')}] " if time and time.strip() else ""


def render_notes(notes: MergedNotes, max_tokens: int | None = None) -> tuple[str, bool]:
    """The merged notes as compact text for the reduce step. When ``max_tokens`` is given and
    the text is too long, the least important material (points, then question-and-answer
    exchanges, then summaries) is cut first; decisions, actions and open questions are always
    kept. Returns ``(text, truncated)``."""

    def build(
        points: list[Point], summaries: list[tuple[str, str]], exchanges: list[Exchange]
    ) -> str:
        parts: list[str] = []
        if summaries:
            parts.append("Summary of each part:")
            parts += [f"- ({rng}) {s}" for rng, s in summaries]
        if points:
            parts.append("\nKey points:")
            parts += [
                f"- {_t(p.time)}{'(' + p.topic.strip() + ') ' if p.topic.strip() else ''}"
                f"{p.speaker + ': ' if p.speaker else ''}{p.text}"
                for p in points
            ]
        if exchanges:  # only with ``detail: high``
            parts.append("\nQuestions and answers:")
            parts += [
                f"- {_t(e.time)}{e.asked_by or 'Someone'} asked: {e.question}"
                + (f" | {e.answered_by or 'Answer'}: {e.answer}" if e.answer else "")
                for e in exchanges
            ]
        parts.append("\nDecisions:")
        parts += [
            f"- {_t(d.time)}{d.text}"
            + (f" (rationale: {d.rationale})" if d.rationale else "")
            + (f" (by {d.by})" if d.by else "")
            for d in notes.decisions
        ] or ["- none recorded"]
        parts.append("\nAction items:")
        parts += [
            f"- {_t(a.time)}{a.owner or 'Unassigned'}: {a.task} (due: {a.due or 'not stated'})"
            for a in notes.actions
        ] or ["- none recorded"]
        parts.append("\nOpen questions:")
        parts += [
            f"- {_t(q.time)}{q.text}" + (f" (raised by {q.raised_by})" if q.raised_by else "")
            for q in notes.questions
        ] or ["- none recorded"]
        return "\n".join(parts).strip()

    points, summaries = list(notes.points), list(notes.summaries)
    exchanges = list(notes.exchanges)
    text = build(points, summaries, exchanges)
    truncated = False
    while (
        max_tokens is not None
        and estimate_tokens(text) > max_tokens
        and (points or summaries or exchanges)
    ):
        truncated = True
        if points:
            points = points[::2] if len(points) > 3 else []  # thin evenly over time
        elif exchanges:
            exchanges = exchanges[::2] if len(exchanges) > 1 else []
        else:
            summaries = summaries[: len(summaries) // 2]
        text = build(points, summaries, exchanges)
    return text, truncated
