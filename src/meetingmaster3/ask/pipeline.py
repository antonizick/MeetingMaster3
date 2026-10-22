"""The Ask agent: a fixed, bounded pipeline driven by the model's JSON (ADR-0049).

1. **Plan**: the question becomes 2-6 search queries (and an optional date range) in one call;
   a bad reply gets one repair request, then the question itself is searched.
2. **Retrieve**: every query goes through 15i's hybrid search; hits are merged by meeting and
   capped at ``ask.max_meetings`` (the reason is kept when capped).
3. **Read**: one call per candidate meeting with its header facts, its Meeting Context section
   and the matching passages with their neighbours, fitted to the model's window. The reply
   says whether the meeting is relevant, what it says, who took part (and in what role) and
   quotes; people and quotes not found in what the model was shown are dropped.
4. **Follow up**: when fewer than two meetings are relevant, one more planning round with the
   findings so far (never more).
5. **Facts** are computed here, not by the model: which meetings are relevant (and so how many),
   their dates, links and attendees, and who spoke on the topic.
6. **Answer**: one call with the findings and facts (never raw transcripts); citations of
   meetings it was not given are removed and recorded.

Nothing here writes files; :mod:`meetingmaster3.ask.notes` saves the result. Consent (S6) is
enforced before the first call, so a refused question sends nothing.
"""

from __future__ import annotations

import datetime as dt
import logging
import math
import re
import time
from collections.abc import Awaitable, Callable, Sequence
from contextlib import AbstractAsyncContextManager, nullcontext
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Literal, Protocol

from pydantic import BaseModel

from meetingmaster3.ask import prompts
from meetingmaster3.ask.schema import (
    AskParseError,
    PersonFinding,
    Plan,
    Reading,
    parse_reply,
)
from meetingmaster3.errors import MM3Error
from meetingmaster3.llm.base import GenerateRequest, LLMBackend, Message
from meetingmaster3.llm.budget import estimate_tokens, usable_tokens, window_for
from meetingmaster3.llm.consent import enforce_consent
from meetingmaster3.markdown.transcript_format import timestamp
from meetingmaster3.search.chunking import PLACEHOLDER_RE
from meetingmaster3.search.query import (
    ContextPassage,
    Hit,
    MeetingFacts,
    SearchFilters,
    SearchResult,
)

log = logging.getLogger(__name__)

PLAN_MAX_TOKENS = 500
READ_MAX_TOKENS = 900
ANSWER_MAX_TOKENS = 1800
EXTRACT_TEMPERATURE = 0.2
NARRATIVE_TEMPERATURE = 0.4
CONTEXT_MARGIN = 0.10
"""Kept free inside ``num_ctx`` over the estimated prompt (as in note generation, ADR-0043)."""
MIN_NUM_CTX = 4096
EXCERPT_CAP_TOKENS = 6000
"""Most excerpt tokens one read call carries, even when a cloud model's window allows more."""
MEETING_CONTEXT_TOKENS = 500
REPAIR_ECHO_CHARS = 1200
HITS_PER_QUERY = 80
SEARCH_CANDIDATES = 120
ASK_VECTOR_MARGIN = 0.12
"""Wider than the Search page's 0.08: the read step judges relevance, so recall matters more."""
NEIGHBOURS = 1
FOLLOW_UP_BELOW = 2
"""Fewer relevant meetings than this allow the one follow-up planning round."""
FOLLOW_UP_QUERIES = 4
REQUEST_TIMEOUT_S = 600.0
_MONTHS = (
    "january|february|march|april|june|july|august|september|october|november|december|"
    "jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec"
)
TIME_WORDS_RE = re.compile(
    rf"\b(?:19|20)\d\d\b|\b\d{{4}}-\d{{2}}(?:-\d{{2}})?\b|\b(?:{_MONTHS})\b|"
    r"\b(?:in|since|before|after|until|during) may\b|\bmay \d|"
    r"\b(?:today|yesterday|ago|since|between|until)\b|"
    r"\b(?:last|past|this|previous|next) (?:week|month|quarter|year|few weeks|few months)\b|"
    r"\bq[1-4]\b",
    re.I,
)
"""The plan's date range is used only when the question talks about time (a small model may
otherwise invent one and hide the meetings)."""
_WIKI_RE = re.compile(r"\[\[([^\[\]|#\n]+)((?:#[^\[\]|\n]*)?)(?:\\?\|([^\[\]\n]*))?\]\]")
_NOTE_TIME_RE = re.compile(r"\[(\d{1,2}:\d{2}(?::\d{2})?)\]")
_NORM_RE = re.compile(r"[^\w\s]")
_TAG_RE = re.compile(r"<(?=[A-Za-z!/?])")
_TABLE_RULE_RE = re.compile(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?$")

ProgressFn = Callable[[float, str], None]
Relevance = Literal["yes", "partly", "no"]


class Retriever(Protocol):
    """What the agent needs from the meeting index (:class:`SearchRetriever` in the app)."""

    async def search(self, text: str, filters: SearchFilters) -> SearchResult: ...

    async def facts(self, mm3_ids: list[str], hits: list[Hit]) -> dict[str, MeetingFacts]: ...

    async def around(self, passage_ids: list[int]) -> dict[int, list[ContextPassage]]: ...

    async def meeting_context(self, note_path: str | None) -> str | None: ...


class Gate(Protocol):
    def hold(self) -> AbstractAsyncContextManager[None]: ...


def _noop_progress(fraction: float, message: str) -> None:
    pass


def norm(text: str) -> str:
    return " ".join(_NORM_RE.sub(" ", text.casefold()).split())


def stem_of(note_path: str | None, title: str) -> str:
    """The wikilink target of a meeting: its note's file name without ``.md``."""
    if note_path:
        return PurePosixPath(note_path).name.removesuffix(".md")
    return title


# -- results --------------------------------------------------------------------------------


@dataclass
class Candidate:
    mm3_id: str
    title: str
    date: str | None
    note_path: str | None
    score: float = 0.0
    hits: list[Hit] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)
    round: int = 0

    @property
    def stem(self) -> str:
        return stem_of(self.note_path, self.title)


@dataclass(frozen=True)
class VerifiedQuote:
    text: str
    start_s: float | None
    """Where the quote is in the recording (transcript passages; a note's own timestamp)."""
    kind: str


@dataclass
class MeetingResult:
    candidate: Candidate
    facts: MeetingFacts | None
    relevance: Relevance | None = None
    """``None`` when the meeting could not be read (see ``error``)."""
    finding: str = ""
    people: list[PersonFinding] = field(default_factory=list)
    quotes: list[VerifiedQuote] = field(default_factory=list)
    dropped_people: list[str] = field(default_factory=list)
    dropped_quotes: int = 0
    excerpt_tokens: int = 0
    passages: int = 0
    passages_left_out: int = 0
    error: str | None = None

    @property
    def relevant(self) -> bool:
        return self.relevance in ("yes", "partly")

    @property
    def mm3_id(self) -> str:
        return self.candidate.mm3_id

    @property
    def title(self) -> str:
        return self.facts.title if self.facts else self.candidate.title

    @property
    def date(self) -> str | None:
        return (self.facts.date if self.facts else None) or self.candidate.date

    @property
    def note_path(self) -> str | None:
        return (self.facts.note_path if self.facts else None) or self.candidate.note_path

    @property
    def stem(self) -> str:
        return stem_of(self.note_path, self.title)

    def attendees(self) -> list[str]:
        if self.facts is None:
            return []
        names = [*self.facts.participants, *self.facts.speakers]
        return [n for n in dict.fromkeys(names) if n and not PLACEHOLDER_RE.match(n)]

    def spoke(self) -> list[str]:
        """People who took part in the topic: the model's people (checked against the excerpts)."""
        return list(dict.fromkeys(p.name for p in self.people))

    def roles(self) -> dict[str, str]:
        return {p.name: p.role for p in self.people if p.role}


@dataclass(frozen=True)
class TableRow:
    date: str | None
    title: str
    stem: str
    mm3_id: str
    note_path: str | None
    relevance: Relevance
    attendees: tuple[str, ...]
    spoke: tuple[str, ...]
    roles: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class PersonRow:
    name: str
    meetings: int
    roles: tuple[str, ...]
    stems: tuple[str, ...]


@dataclass
class PlanRecord:
    round: int
    queries: list[str]
    source: Literal["model", "repaired", "fallback"]
    date_from: str | None = None
    date_to: str | None = None
    dates_ignored: bool = False
    dates_dropped: bool = False
    """The plan's dates found nothing, so the archive was searched without them."""
    error: str | None = None


@dataclass
class Trace:
    plans: list[PlanRecord] = field(default_factory=list)
    search_modes: dict[str, str] = field(default_factory=dict)
    search_reason: str | None = None
    candidates: int = 0
    capped: str | None = None
    read: int = 0
    unread: list[str] = field(default_factory=list)
    follow_up: bool = False
    follow_up_reason: str | None = None
    stripped: list[str] = field(default_factory=list)
    fixed: list[str] = field(default_factory=list)
    findings_trimmed: bool = False
    tables_dropped: int = 0
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0
    window: int = 0
    num_ctx: int = 0
    previous_question: str | None = None


@dataclass
class AskResult:
    question: str
    answer: str
    """The model's Markdown answer, citations checked (or the code's "nothing found" text)."""
    meetings: list[MeetingResult]
    """Every meeting read, best first."""
    rows: list[TableRow]
    people: list[PersonRow]
    wants: list[str]
    topic: str
    trace: Trace
    backend: str
    model: str
    is_local: bool
    started_at: dt.datetime

    @property
    def relevant(self) -> list[MeetingResult]:
        return [m for m in self.meetings if m.relevant]

    @property
    def count(self) -> int:
        return len(self.rows)

    def findings(self) -> list[str]:
        return [
            f"{r.stem} ({r.date or 'no date'}): {r.finding}" for r in self.relevant if r.finding
        ]


# -- pure helpers ---------------------------------------------------------------------------


def merge_candidates(
    results: Sequence[tuple[str, SearchResult]], round_no: int = 0
) -> list[Candidate]:
    """Meetings found by any query, best first: a meeting's score adds its best passage score
    from each query that found it, so a meeting several queries agree on ranks higher."""
    out: dict[str, Candidate] = {}
    for query, result in results:
        for group in result.group_by_meeting():
            c = out.get(group.mm3_id)
            if c is None:
                c = out[group.mm3_id] = Candidate(
                    group.mm3_id, group.title, group.date, group.note_path, round=round_no
                )
            c.score += group.score
            c.queries.append(query)
            seen = {h.passage_id for h in c.hits}
            c.hits += [h for h in group.hits if h.passage_id not in seen]
            if c.note_path is None and group.note_path:
                c.note_path = group.note_path
    ranked = sorted(out.values(), key=lambda c: (-c.score, -len(c.hits), c.date or "", c.title))
    for c in ranked:
        c.hits.sort(key=lambda h: -h.score)
    return ranked


def cap_candidates(candidates: list[Candidate], limit: int) -> tuple[list[Candidate], str | None]:
    if len(candidates) <= limit:
        return candidates, None
    return candidates[:limit], (
        f"{len(candidates)} meetings matched the searches; the {limit} best were read "
        "(Settings → Search & Ask → Most meetings read per question)."
    )


def question_mentions_time(question: str) -> bool:
    return bool(TIME_WORDS_RE.search(question))


def _fmt_time(seconds: float | None) -> str:
    return timestamp(seconds) if seconds is not None else ""


def render_passage(p: ContextPassage) -> str:
    if p.kind == "transcript":
        span = " to ".join(t for t in (_fmt_time(p.start_s), _fmt_time(p.end_s)) if t)
        return f"[Transcript {span}]\n{p.body}".rstrip()
    return f"[Note · {p.heading or 'text'}]\n{p.body}".rstrip()


def meeting_header(c: Candidate, facts: MeetingFacts | None) -> str:
    lines = [f"Title: {facts.title if facts else c.title}", f"Date: {c.date or 'unknown'}"]
    if facts and facts.participants:
        lines.append(f"Participants: {', '.join(facts.participants)}")
    if facts and facts.speakers:
        lines.append(f"Speakers in the recording: {', '.join(facts.speakers)}")
    return "\n".join(lines)


def clip_tokens(text: str, tokens: int) -> str:
    limit = tokens * 4
    if len(text) <= limit:
        return text
    cut = text.rfind("\n", 0, limit)
    return text[: cut if cut > limit // 2 else limit].rstrip() + "\n…"


def select_passages(
    hits: Sequence[Hit],
    around: dict[int, list[ContextPassage]],
    budget_tokens: int,
) -> tuple[list[ContextPassage], int]:
    """The passages to show for a meeting: each hit (best first) with its neighbours while they
    fit ``budget_tokens``, returned in file order (notes first). Also returns how many hits did
    not fit."""
    chosen: dict[int, ContextPassage] = {}
    used = 0
    left_out = 0
    for hit in hits:
        group = around.get(hit.passage_id) or []
        own = next((p for p in group if p.passage_id == hit.passage_id), None)
        if own is None:
            continue
        for p in (own, *(p for p in group if p is not own)):
            if p.passage_id in chosen:
                continue
            cost = estimate_tokens(render_passage(p)) + 2
            if used + cost > budget_tokens:
                if p is own:
                    left_out += 1
                break
            chosen[p.passage_id] = p
            used += cost
    out = sorted(chosen.values(), key=lambda p: (p.kind != "note", p.doc_id, p.ord))
    return out, left_out


def known_names(facts: MeetingFacts | None) -> list[str]:
    if facts is None:
        return []
    names = [*facts.participants, *facts.speakers, *facts.speakers_in_hits]
    return [n for n in dict.fromkeys(names) if n and not PLACEHOLDER_RE.match(n)]


def match_person(name: str, known: Sequence[str], shown_text: str) -> str | None:
    """The person's name as the files spell it, or ``None`` if the excerpts do not show them."""
    key = norm(name)
    if not key or PLACEHOLDER_RE.match(name):
        return None
    for k in known:
        if norm(k) == key:
            return k
    words = set(key.split())
    partial = [k for k in known if words and words <= set(norm(k).split())]
    if len(partial) == 1:
        return partial[0]
    if f" {key} " in f" {norm(shown_text)} ":
        return " ".join(name.split())
    return None


def verify_quote(text: str, passages: Sequence[ContextPassage]) -> VerifiedQuote | None:
    """A quote kept only if it is in one of the passages shown (word for word, punctuation and
    case aside, or all but one of its words in order for longer quotes)."""
    key = norm(text)
    if not key:
        return None
    for p in passages:
        body = norm(p.body)
        if key in body or _near_match(key.split(), body.split()):
            start = p.start_s if p.kind == "transcript" else _note_time(p.body, text)
            return VerifiedQuote(text=text, start_s=start, kind=p.kind)
    return None


def _near_match(words: list[str], body: list[str]) -> bool:
    if len(words) < 6:
        return False
    hits = 0
    pos = 0
    for w in words:
        try:
            pos = body.index(w, pos) + 1
            hits += 1
        except ValueError:
            continue
    return hits >= len(words) - 1


def _note_time(body: str, quote: str) -> float | None:
    """A note line's own ``[hh:mm:ss]`` reference, for a quote taken from that line."""
    first = norm(quote).split()[:4]
    for line in body.split("\n"):
        if first and " ".join(first) in norm(line):
            m = _NOTE_TIME_RE.search(line)
            if m:
                parts = [int(x) for x in m.group(1).split(":")]
                while len(parts) < 3:
                    parts.insert(0, 0)
                return float(parts[0] * 3600 + parts[1] * 60 + parts[2])
    return None


def build_rows(meetings: Sequence[MeetingResult]) -> list[TableRow]:
    rows = [
        TableRow(
            date=m.date,
            title=m.title,
            stem=m.stem,
            mm3_id=m.mm3_id,
            note_path=m.note_path,
            relevance=m.relevance or "no",
            attendees=tuple(m.attendees()),
            spoke=tuple(m.spoke()),
            roles=tuple(m.roles().items()),
        )
        for m in meetings
        if m.relevant
    ]
    rows.sort(key=lambda r: (r.date or "9999", r.title))
    return rows


def build_people(rows: Sequence[TableRow]) -> list[PersonRow]:
    counts: dict[str, list[TableRow]] = {}
    for row in rows:
        for name in row.spoke:
            counts.setdefault(name, []).append(row)
    people = []
    for name, mine in counts.items():
        roles = [role for r in mine for n, role in r.roles if n == name and role]
        people.append(
            PersonRow(
                name=name,
                meetings=len(mine),
                roles=tuple(dict.fromkeys(roles)),
                stems=tuple(r.stem for r in mine),
            )
        )
    people.sort(key=lambda p: (-p.meetings, p.name))
    return people


def facts_text(rows: Sequence[TableRow], people: Sequence[PersonRow], read: int) -> str:
    deep = sum(1 for r in rows if r.relevance == "yes")
    lines = [
        f"Meetings that discuss the topic: {len(rows)} ({deep} in depth, {len(rows) - deep} "
        f"briefly), out of {read} meetings read."
    ]
    for r in rows:
        lines.append(
            f"- [[{r.stem}]] · {r.date or 'no date'} · "
            f"{'in depth' if r.relevance == 'yes' else 'briefly'} · attendees: "
            f"{', '.join(r.attendees) or 'not recorded'}"
        )
    if people:
        lines.append("People who took part in the topic (meetings):")
        for p in people:
            role = f"; stated role: {', '.join(p.roles)}" if p.roles else ""
            lines.append(f"- {p.name}: {p.meetings}{role}")
    return "\n".join(lines)


def findings_text(meetings: Sequence[MeetingResult], level: int = 0) -> str:
    """The per-meeting findings for the answer call. ``level`` shortens them (1: no quotes,
    2: findings cut to 200 characters, 3: brief meetings without detail)."""
    blocks = []
    for m in sorted(meetings, key=lambda m: (m.date or "9999", m.title)):
        if not m.relevant:
            continue
        if level >= 3 and m.relevance == "partly":
            blocks.append(f"[[{m.stem}]] ({m.date or 'no date'}): touched on briefly.")
            continue
        finding = m.finding if level < 2 else m.finding[:200]
        lines = [f"[[{m.stem}]] ({m.date or 'no date'}, {m.relevance}): {finding}"]
        for p in m.people:
            bits = [p.name]
            if p.role:
                bits.append(f"role: {p.role}")
            if p.contribution and level < 2:
                bits.append(p.contribution)
            lines.append("  - " + "; ".join(bits))
        if level < 1:
            for q in m.quotes:
                when = f" [{_fmt_time(q.start_s)}]" if q.start_s is not None else ""
                lines.append(f'  - quote{when}: "{q.text}"')
        blocks.append("\n".join(lines))
    return "\n".join(blocks)


def check_citations(
    text: str, stems: Sequence[str], titles: dict[str, str] | None = None
) -> tuple[str, list[str], list[str]]:
    """Keep ``[[links]]`` to the meetings the model was given and turn every other one into plain
    text. A link to a given meeting's title instead of its file name is corrected. Returns the
    text, the removed targets and the corrected ones."""
    allowed = {s.casefold(): s for s in stems}
    by_title = {k.casefold(): v for k, v in (titles or {}).items()}
    stripped: list[str] = []
    fixed: list[str] = []

    def sub(m: re.Match[str]) -> str:
        target, heading, alias = m.group(1).strip(), m.group(2) or "", m.group(3)
        key = target.removesuffix(".md").casefold()
        if key in allowed:
            stem = allowed[key]
        elif key in by_title:
            stem = by_title[key]
            fixed.append(target)
        else:
            stripped.append(target)
            return alias or target
        return f"[[{stem}{heading}|{alias}]]" if alias else f"[[{stem}{heading}]]"

    return _WIKI_RE.sub(sub, text), stripped, fixed


def clean_answer(text: str) -> str:
    """The model's Markdown with reasoning blocks removed and HTML tags neutralised (the vault
    note is rendered by Obsidian, which would otherwise show raw HTML)."""
    text = re.sub(r"<(think|thinking|reasoning)>.*?</\1>", "", text, flags=re.S | re.I)
    text = text.strip()
    if text.startswith("```") and text.endswith("```"):
        text = text.strip("`").removeprefix("markdown").strip()
    return _TAG_RE.sub("&lt;", text)


def drop_tables(text: str) -> tuple[str, int]:
    """Remove Markdown tables the model drew anyway (the table of meetings is built from the
    files and added after the answer). Returns the text and how many tables were removed."""
    lines = text.split("\n")
    out: list[str] = []
    dropped = 0
    i = 0
    while i < len(lines):
        j = i
        while j < len(lines) and lines[j].lstrip().startswith("|"):
            j += 1
        if j - i >= 2 and _TABLE_RULE_RE.match(lines[i + 1].strip()):
            dropped += 1
            i = j
            continue
        out.append(lines[i])
        i += 1
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip(), dropped


def nothing_found(question: str, plans: Sequence[PlanRecord], read: int, candidates: int) -> str:
    searched = "; ".join(f"“{q}”" for p in plans for q in p.queries)
    if not candidates:
        return (
            "**No meetings were found for this question.** The meeting index had no passages "
            f"matching the searches: {searched}.\n\nTry other words, or check that the meetings "
            "are indexed (Settings → Search & Ask)."
        )
    return (
        f"**None of the {read} meetings read discusses this**, as far as the model could tell "
        f"from their notes and transcripts. Searched for: {searched}.\n\nTry other words or a "
        "wider date range."
    )


def enforce_ask_consent(backend: LLMBackend, cloud_consent: bool, remembered: bool) -> None:
    """S6 for Ask: a cloud backend needs this question's consent or the backend's own "Always
    allow Ask AI agent" switch (``ask_consent_remembered``); the note-writing switch does not
    count."""
    try:
        enforce_consent(backend, cloud_consent=cloud_consent, remembered=remembered)
    except MM3Error as exc:
        raise MM3Error(
            exc.code,
            f"The backend '{backend.id}' would send excerpts of your meetings to a cloud service.",
            "Tick the box for this question (mm3 ask: --allow-cloud), turn on “Always allow Ask AI "
            "agent” for this backend in Settings → Language models, or choose a local model.",
            status_code=exc.status_code,
        ) from exc


# -- the agent ------------------------------------------------------------------------------


@dataclass
class AskAgent:
    backend: LLMBackend
    model: str
    retriever: Retriever
    backend_name: str = ""
    cloud_consent: bool = False
    consent_remembered: bool = False
    """The backend's ``ask_consent_remembered`` (never ``consent_remembered``)."""
    max_meetings: int = 25
    max_context: int | None = None
    filters: SearchFilters = field(default_factory=SearchFilters)
    """The user's own filters (Ask page or CLI); they always apply."""
    previous: tuple[str, list[str]] | None = None
    """``(question, findings)`` of the answer this one follows up."""
    gate: Gate | None = None
    """The job runner's GPU, held for each call to a local model (R5)."""
    progress: ProgressFn = _noop_progress
    today: dt.date | None = None
    trace: Trace = field(default_factory=Trace)
    _fraction: float = 0.0

    def _report(self, fraction: float, message: str) -> None:
        self._fraction = fraction
        self.progress(fraction, message)

    # -- model calls --------------------------------------------------------------------

    async def _window(self) -> int:
        window = await window_for(self.backend, self.model)
        if self.max_context and self.backend.is_local:
            window = min(window, self.max_context)
        return window

    def _gate(self) -> AbstractAsyncContextManager[None]:
        if self.gate is not None and self.backend.is_local:
            busy = getattr(self.gate, "busy", None)
            if callable(busy) and busy():
                self.progress(self._fraction, "Waiting for the meeting being processed to finish")
            return self.gate.hold()
        return nullcontext()

    async def _call(
        self,
        system: str,
        messages: list[Message],
        *,
        temperature: float,
        max_tokens: int,
        json_mode: bool = True,
    ) -> str:
        async with self._gate():
            self.trace.calls += 1
            result = await self.backend.generate(
                GenerateRequest(
                    model=self.model,
                    system=system,
                    messages=tuple(messages),
                    temperature=temperature,
                    max_tokens=max_tokens,
                    json_mode=json_mode,
                    num_ctx=self.trace.num_ctx or None,
                    timeout=REQUEST_TIMEOUT_S,
                    think=False,
                )
            )
        if result.usage is not None:
            self.trace.input_tokens += result.usage.input_tokens or 0
            self.trace.output_tokens += result.usage.output_tokens or 0
        return result.text

    async def _json[T: BaseModel](
        self, system: str, prompt: str, schema: str, model: type[T], max_tokens: int
    ) -> tuple[T, bool]:
        """One JSON call with one repair request. Returns the object and whether it needed the
        repair; raises :class:`AskParseError` if the repair fails too."""
        messages = [Message("user", prompt)]
        reply = await self._call(
            system, messages, temperature=EXTRACT_TEMPERATURE, max_tokens=max_tokens
        )
        try:
            return parse_reply(reply, model), False
        except AskParseError as exc:
            messages += [
                Message("assistant", reply[:REPAIR_ECHO_CHARS]),
                Message("user", prompts.repair_prompt(str(exc), schema)),
            ]
        reply = await self._call(
            system, messages, temperature=EXTRACT_TEMPERATURE, max_tokens=max_tokens
        )
        return parse_reply(reply, model), True

    # -- steps --------------------------------------------------------------------------

    async def plan(self, question: str, round_no: int, context: str | None) -> Plan:
        today = self.today or dt.date.today()
        try:
            plan, repaired = await self._json(
                prompts.PLAN_SYSTEM,
                prompts.plan_prompt(question, today, context),
                prompts.PLAN_SCHEMA,
                Plan,
                PLAN_MAX_TOKENS,
            )
            source: Literal["model", "repaired", "fallback"] = "repaired" if repaired else "model"
            error = None
        except AskParseError as exc:
            plan = Plan(queries=[question])
            source, error = "fallback", str(exc)
        record = PlanRecord(round_no, list(plan.queries), source, error=error)
        if plan.date_from or plan.date_to:
            if (
                self.filters.date_from
                or self.filters.date_to
                or not question_mentions_time(question)
            ):
                record.dates_ignored = True
                plan.date_from = plan.date_to = None
            else:
                record.date_from, record.date_to = plan.date_from, plan.date_to
        self.trace.plans.append(record)
        return plan

    async def retrieve(self, plan: Plan, round_no: int) -> list[Candidate]:
        base = self.filters
        filters = SearchFilters(
            date_from=base.date_from or plan.date_from,
            date_to=base.date_to or plan.date_to,
            people=base.people,
            kinds=base.kinds,
            mm3_ids=base.mm3_ids,
        )
        found = await self._search_all(plan.queries, filters, round_no)
        planned_dates = (plan.date_from, plan.date_to) != (None, None)
        if not found and planned_dates and not (base.date_from or base.date_to):
            # The model's date range (not the user's) left nothing: search the whole archive.
            self.trace.plans[-1].dates_dropped = True
            filters = SearchFilters(people=base.people, kinds=base.kinds, mm3_ids=base.mm3_ids)
            found = await self._search_all(plan.queries, filters, round_no)
        return found

    async def _search_all(
        self, queries: Sequence[str], filters: SearchFilters, round_no: int
    ) -> list[Candidate]:
        results: list[tuple[str, SearchResult]] = []
        for query in queries:
            result = await self.retriever.search(query, filters)
            self.trace.search_modes[query] = result.mode
            if result.reason and self.trace.search_reason is None:
                self.trace.search_reason = result.reason
            results.append((query, result))
        return merge_candidates(results, round_no)

    async def read(self, question: str, c: Candidate, facts: MeetingFacts | None) -> MeetingResult:
        out = MeetingResult(candidate=c, facts=facts)
        header = meeting_header(c, facts)
        context = await self.retriever.meeting_context(c.note_path)
        if context:
            header += "\n\nMeeting Context (from the note):\n" + clip_tokens(
                context, MEETING_CONTEXT_TOKENS
            )
        skeleton = prompts.read_prompt(question, header, "")
        capacity = self._capacity()
        repair_room = estimate_tokens(prompts.repair_prompt("x" * 80, prompts.READ_SCHEMA)) + (
            REPAIR_ECHO_CHARS // 4
        )
        budget = min(
            EXCERPT_CAP_TOKENS,
            capacity
            - estimate_tokens(prompts.READ_SYSTEM + skeleton)
            - READ_MAX_TOKENS
            - repair_room,
        )
        if budget < 200:
            out.error = "the model's context window is too small to read this meeting"
            return out
        around = await self.retriever.around([h.passage_id for h in c.hits])
        passages, left_out = select_passages(c.hits, around, budget)
        out.passages, out.passages_left_out = len(passages), left_out
        excerpts = "\n\n".join(render_passage(p) for p in passages)
        out.excerpt_tokens = estimate_tokens(excerpts)
        try:
            reading, _ = await self._json(
                prompts.READ_SYSTEM,
                prompts.read_prompt(question, header, excerpts),
                prompts.READ_SCHEMA,
                Reading,
                READ_MAX_TOKENS,
            )
        except AskParseError as exc:
            out.error = f"the model's reply could not be used ({exc})"
            return out
        out.relevance = reading.relevant
        out.finding = reading.finding if reading.relevant != "no" else ""
        if not out.relevant:
            return out
        shown = header + "\n" + excerpts
        known = known_names(facts)
        for person in reading.people:
            name = match_person(person.name, known, shown)
            if name is None:
                out.dropped_people.append(person.name)
            elif name not in {p.name for p in out.people}:
                out.people.append(person.model_copy(update={"name": name}))
        for quote in reading.quotes:
            verified = verify_quote(quote.text, passages)
            if verified is None:
                out.dropped_quotes += 1
            else:
                out.quotes.append(verified)
        return out

    async def _read_all(
        self,
        question: str,
        candidates: list[Candidate],
        results: list[MeetingResult],
        done_before: int,
        total: int,
    ) -> None:
        facts = await self.retriever.facts(
            [c.mm3_id for c in candidates], [h for c in candidates for h in c.hits]
        )
        for i, c in enumerate(candidates, start=1):
            position = done_before + i
            self._report(
                0.12 + 0.73 * (position - 1) / max(total, 1),
                f"Reading meeting {position} of {total}: {c.title}",
            )
            result = await self.read(question, c, facts.get(c.mm3_id))
            if result.error:
                self.trace.unread.append(f"{c.title}: {result.error}")
            results.append(result)
            self.trace.read += 1

    async def answer(
        self,
        question: str,
        plan: Plan,
        meetings: list[MeetingResult],
        rows: list[TableRow],
        people: list[PersonRow],
    ) -> str:
        wants = list(plan.wants)
        context = None
        if self.previous is not None:
            context = prompts.previous_answer_context(*self.previous)
        facts = facts_text(rows, people, self.trace.read)
        capacity = self._capacity()
        prompt = ""
        for level in range(4):
            prompt = prompts.answer_prompt(
                question, facts, findings_text(meetings, level), wants, context
            )
            if estimate_tokens(prompts.ANSWER_SYSTEM + prompt) + ANSWER_MAX_TOKENS <= capacity:
                break
            self.trace.findings_trimmed = True
        text = await self._call(
            prompts.ANSWER_SYSTEM,
            [Message("user", prompt)],
            temperature=NARRATIVE_TEMPERATURE,
            max_tokens=ANSWER_MAX_TOKENS,
            json_mode=False,
        )
        text, tables = drop_tables(clean_answer(text))
        self.trace.tables_dropped += tables
        stems = [r.stem for r in rows]
        titles = {r.title: r.stem for r in rows}
        text, stripped, fixed = check_citations(text, stems, titles)
        self.trace.stripped += stripped
        self.trace.fixed += fixed
        if not text:
            raise MM3Error(
                "E_ASK_EMPTY",
                "The model returned an empty answer.",
                "Try again, or choose another model.",
            )
        return text

    # -- run ----------------------------------------------------------------------------

    async def run(self, question: str) -> AskResult:
        started_at = dt.datetime.now().astimezone()
        started = time.monotonic()
        question = " ".join(question.split())
        if not question:
            raise MM3Error("E_ASK_EMPTY_QUESTION", "Type a question first.", "", status_code=422)
        enforce_ask_consent(self.backend, self.cloud_consent, self.consent_remembered)
        if self.previous is not None:
            self.trace.previous_question = self.previous[0]
        self.trace.window = await self._window()
        self.trace.num_ctx = self._num_ctx(self.trace.window)
        self._report(0.01, "Planning the searches")
        context = (
            prompts.previous_answer_context(*self.previous) if self.previous is not None else None
        )
        plan = await self.plan(question, 0, context)
        self._report(0.08, "Searching the meetings")
        found = await self.retrieve(plan, 0)
        self.trace.candidates = len(found)
        candidates, self.trace.capped = cap_candidates(found, self.max_meetings)
        results: list[MeetingResult] = []
        await self._read_all(question, candidates, results, 0, len(candidates))
        relevant = sum(1 for r in results if r.relevant)
        if relevant < FOLLOW_UP_BELOW and self.trace.read < self.max_meetings:
            self.trace.follow_up = True
            self.trace.follow_up_reason = (
                f"{relevant} relevant meeting{'' if relevant == 1 else 's'} after the first round"
            )
            self._report(0.5, "Planning more searches")
            done = [q for p in self.trace.plans for q in p.queries]
            more = await self.plan(
                question,
                1,
                prompts.follow_up_context(done, [f for r in results for f in [r.finding] if f]),
            )
            seen_q = {q.casefold() for q in done}
            more.queries = [q for q in more.queries if q.casefold() not in seen_q][
                :FOLLOW_UP_QUERIES
            ]
            self.trace.plans[-1].queries = list(more.queries)
            if more.queries:
                new = await self.retrieve(more, 1)
                read_ids = {r.mm3_id for r in results}
                new = [c for c in new if c.mm3_id not in read_ids]
                self.trace.candidates += len(new)
                room = self.max_meetings - self.trace.read
                extra, capped = cap_candidates(new, room)
                if capped:
                    self.trace.capped = capped
                await self._read_all(
                    question, extra, results, self.trace.read, self.trace.read + len(extra)
                )
        rows = build_rows(results)
        people = build_people(rows)
        if rows:
            self._report(0.86, "Writing the answer")
            text = await self.answer(question, plan, results, rows, people)
        else:
            text = nothing_found(question, self.trace.plans, self.trace.read, self.trace.candidates)
        self.trace.seconds = time.monotonic() - started
        results.sort(key=lambda r: (not r.relevant, r.relevance != "yes", r.date or "9999"))
        return AskResult(
            question=question,
            answer=text,
            meetings=results,
            rows=rows,
            people=people,
            wants=list(plan.wants),
            topic=plan.topic,
            trace=self.trace,
            backend=self.backend_name or self.backend.id,
            model=self.model,
            is_local=self.backend.is_local,
            started_at=started_at,
        )

    def _capacity(self) -> int:
        """Estimated tokens one call may use (prompt and reply), inside the window's usable share
        and ``num_ctx`` less its margin."""
        return min(usable_tokens(self.trace.window), int(self.trace.num_ctx / (1 + CONTEXT_MARGIN)))

    def _num_ctx(self, window: int) -> int:
        """One context size for every call of a question, so a local Ollama never reloads the
        model between calls: room for the largest read call (excerpts capped) plus the margin."""
        if not self.backend.is_local:
            return window
        need = EXCERPT_CAP_TOKENS + MEETING_CONTEXT_TOKENS + READ_MAX_TOKENS + 1500
        wanted = math.ceil(need * (1 + CONTEXT_MARGIN) / 1024) * 1024
        return min(window, max(MIN_NUM_CTX, wanted))


# -- the index adapter ----------------------------------------------------------------------


Reader = Callable[[str], Awaitable[str | None]]


@dataclass
class SearchRetriever:
    """:class:`Retriever` over the app's ``SearchService`` and the vault."""

    service: Any
    meeting_context_reader: Reader | None = None

    async def search(self, text: str, filters: SearchFilters) -> SearchResult:
        result: SearchResult = await self.service.query(
            text,
            limit=HITS_PER_QUERY,
            filters=filters,
            candidates=SEARCH_CANDIDATES,
            vector_margin=ASK_VECTOR_MARGIN,
        )
        return result

    async def facts(self, mm3_ids: list[str], hits: list[Hit]) -> dict[str, MeetingFacts]:
        facts: dict[str, MeetingFacts] = await self.service.meeting_facts(mm3_ids, hits)
        return facts

    async def around(self, passage_ids: list[int]) -> dict[int, list[ContextPassage]]:
        found: dict[int, list[ContextPassage]] = await self.service.passages_around(
            passage_ids, NEIGHBOURS
        )
        return found

    async def meeting_context(self, note_path: str | None) -> str | None:
        if note_path is None or self.meeting_context_reader is None:
            return None
        try:
            return await self.meeting_context_reader(note_path)
        except (OSError, MM3Error) as exc:
            log.info("Meeting Context not read from %s: %s", note_path, exc)
            return None


def meeting_context_from(text: str) -> str | None:
    """The body of a note's Meeting Context section (Default Notes), if it has one."""
    from meetingmaster3.domain.note import Section
    from meetingmaster3.markdown.note_parser import parse_note

    try:
        note = parse_note(text).note
    except MM3Error:
        return None
    for block in note.blocks:
        if isinstance(block, Section) and (
            block.id == "meeting-context" or block.title.strip().casefold() == "meeting context"
        ):
            body = block.body_markdown.strip()
            return body or None
    return None
