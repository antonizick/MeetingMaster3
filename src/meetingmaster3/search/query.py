"""Hybrid search over the meeting index: words (FTS5, BM25) and meaning (embeddings), fused.

The user's text never reaches FTS5 as syntax: it is split into word tokens, common words are
dropped, and each remaining token is quoted, so quotes, ``NEAR``, ``*``, ``-``, ``:`` or
parentheses cannot break or widen the query (:func:`fts_query`). Vector search is a brute-force
cosine over every stored vector of the current model (vectors are unit length from the models
used, and are normalised here anyway); at tens of thousands of passages this takes milliseconds
(``docs/PERFORMANCE.md``). The two ranked lists are fused by reciprocal rank (k = 60).

Without vectors (no embedder, Ollama stopped, no consent) the search is words only and says why.
"""

from __future__ import annotations

import asyncio
import heapq
import json
import logging
import math
import operator
import re
import sqlite3
import time
from array import array
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from meetingmaster3.errors import MM3Error
from meetingmaster3.markdown.transcript_format import timestamp
from meetingmaster3.search.chunking import PLACEHOLDER_RE
from meetingmaster3.search.embedder import EmbedderChoice
from meetingmaster3.search.store import SearchStore, unpack

log = logging.getLogger(__name__)

RRF_K = 60
HEAD_WEIGHT = 0.3
"""BM25 weight of a passage's heading lines (title, date, section, speakers) against its body
(1.0). Every passage repeats its meeting's title, so a word that is only in the title would
otherwise match every passage of that meeting as strongly as the passage that discusses it."""
WORD_FRACTION = 0.3
"""Word candidates must score at least this fraction of the best BM25 score: a passage matching
one common query word should not enter the fusion at the rank of one that matches them all."""
VECTOR_MARGIN = 0.08
"""Vector candidates must score within this much cosine similarity of the best one. Embedding
models give unrelated text a similarity well above zero (about 0.5 for nomic-embed-text), so a
plain top-N would always "find" every meeting; relevant passages stand out by a few hundredths
(measured on the synthetic corpus and on Nick's vault, ADR-0050)."""
MAX_TERMS = 32
MAX_TERM_CHARS = 64
MAX_QUERY_CHARS = 2000
SNIPPET_CHARS = 280
STOPWORDS = frozenset(
    """a about above after again all am an and any are as at be been before being below between
    both but by can could did do does doing down during each few for from further had has have
    having he her here hers him his how i if in into is it its just me more most my no nor not
    now of off on once only or other our ours out over own same she should so some such than
    that the their theirs them then there these they this those through to too under until up
    very was we were what when where which while who whom why will with would you your yours
    discuss discussed discussion discussions meeting meetings talk talked time times""".split()  # noqa: SIM905
)
"""Dropped from the word query (they would match nearly every passage). Meaning search sees the
whole question."""
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_HEAD_RE = re.compile(r"^(## .*|Transcript|Speakers: .*)$")

Mode = Literal["hybrid", "words", "meaning", "none"]


@dataclass(frozen=True)
class SearchFilters:
    date_from: str | None = None
    """``YYYY-MM-DD``, inclusive."""
    date_to: str | None = None
    people: tuple[str, ...] = ()
    """Meetings where any of these names is a participant or a speaker (case-insensitive, part
    of a name matches)."""
    kinds: tuple[str, ...] = ()
    """``note`` and/or ``transcript``; empty means both."""
    mm3_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Hit:
    passage_id: int
    mm3_id: str
    kind: str
    path: str
    """The file the passage is in (vault-relative)."""
    note_path: str | None
    """The meeting's note (vault-relative), for links; ``None`` if only its transcript is
    indexed."""
    title: str
    date: str | None
    text: str
    """The whole passage, as embedded (title, heading or speakers first)."""
    body: str
    """The passage without its heading lines."""
    heading: str | None
    section_id: str | None
    start_s: float | None
    end_s: float | None
    speakers: tuple[str, ...]
    score: float
    word_rank: int | None = None
    word_score: float | None = None
    """BM25 (lower is better, as SQLite reports it)."""
    vector_rank: int | None = None
    vector_score: float | None = None
    """Cosine similarity (-1 to 1)."""
    snippet: tuple[tuple[str, bool], ...] = ()
    """The best part of ``body`` as (text, matched) pieces; render ``matched`` highlighted."""

    def label(self) -> str:
        """Where the passage is: the section heading, or "Transcript · 0:12:30 · names"."""
        if self.kind == "transcript":
            when = timestamp(self.start_s) if self.start_s is not None else ""
            return " · ".join(p for p in ("Transcript", when, ", ".join(self.speakers)) if p)
        return self.heading or "Note"

    def snippet_text(self, open_mark: str = "**", close_mark: str = "**") -> str:
        return "".join(f"{open_mark}{t}{close_mark}" if hit else t for t, hit in self.snippet)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passage_id": self.passage_id,
            "mm3_id": self.mm3_id,
            "kind": self.kind,
            "path": self.path,
            "note_path": self.note_path,
            "title": self.title,
            "date": self.date,
            "heading": self.heading,
            "section_id": self.section_id,
            "start_s": self.start_s,
            "end_s": self.end_s,
            "speakers": list(self.speakers),
            "score": round(self.score, 6),
            "word_rank": self.word_rank,
            "word_score": self.word_score,
            "vector_rank": self.vector_rank,
            "vector_score": None if self.vector_score is None else round(self.vector_score, 4),
            "snippet": self.snippet_text(),
            "text": self.text,
        }


@dataclass(frozen=True)
class MeetingHits:
    mm3_id: str
    title: str
    date: str | None
    note_path: str | None
    score: float
    hits: tuple[Hit, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mm3_id": self.mm3_id,
            "title": self.title,
            "date": self.date,
            "note_path": self.note_path,
            "score": round(self.score, 6),
            "hits": [h.to_dict() for h in self.hits],
        }


def group_by_meeting(hits: Iterable[Hit]) -> list[MeetingHits]:
    """Meetings ranked by their best passage (then by how many passages matched), each with all
    its hits in rank order."""
    groups: dict[str, list[Hit]] = {}
    for hit in hits:
        groups.setdefault(hit.mm3_id, []).append(hit)
    out = []
    for mm3_id, items in groups.items():
        items.sort(key=lambda h: -h.score)
        note = next((h for h in items if h.kind == "note"), items[0])
        out.append(
            MeetingHits(
                mm3_id=mm3_id,
                title=note.title,
                date=note.date,
                note_path=note.note_path,
                score=items[0].score,
                hits=tuple(items),
            )
        )
    out.sort(key=lambda m: (-m.score, -len(m.hits), m.date or "", m.title))
    return out


@dataclass
class SearchResult:
    query: str
    hits: list[Hit]
    mode: Mode
    reason: str | None = None
    """Why meaning search was not used (``mode == "words"``), for the user."""
    embedder: str | None = None
    """The embedder's badge: ``local`` or ``cloud: <kind>``."""
    timings_ms: dict[str, float] = field(default_factory=dict)

    def group_by_meeting(self) -> list[MeetingHits]:
        return group_by_meeting(self.hits)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "mode": self.mode,
            "reason": self.reason,
            "embedder": self.embedder,
            "timings_ms": {k: round(v, 1) for k, v in self.timings_ms.items()},
            "meetings": [m.to_dict() for m in self.group_by_meeting()],
        }


@dataclass(frozen=True)
class MeetingFacts:
    """What the files say about a meeting (for code-built tables in Phase 15j)."""

    mm3_id: str
    title: str
    date: str | None
    participants: tuple[str, ...]
    """From the note's ``participants`` property."""
    speakers: tuple[str, ...]
    """Named speakers of the transcript (``mm3-speakers``), placeholders left out."""
    speakers_in_hits: tuple[str, ...]
    """Named speakers of the given hits, in order of first appearance."""
    note_path: str | None
    transcript_path: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "mm3_id": self.mm3_id,
            "title": self.title,
            "date": self.date,
            "participants": list(self.participants),
            "speakers": list(self.speakers),
            "speakers_in_hits": list(self.speakers_in_hits),
            "note_path": self.note_path,
            "transcript_path": self.transcript_path,
        }


# -- FTS5 ------------------------------------------------------------------------------------


def query_terms(text: str) -> list[str]:
    """The words of ``text`` worth searching for: lower-cased, common words dropped, each at most
    64 characters, at most 32 (first occurrences)."""
    terms: list[str] = []
    for token in _TOKEN_RE.findall(text[:MAX_QUERY_CHARS].casefold()):
        token = token.strip("_")[:MAX_TERM_CHARS]
        if not token or token in STOPWORDS or (len(token) == 1 and not token.isdigit()):
            continue
        if token not in terms:
            terms.append(token)
        if len(terms) == MAX_TERMS:
            break
    return terms


def fts_query(text: str) -> str | None:
    """A safe FTS5 MATCH expression for ``text``: every term quoted, joined by OR (BM25 ranks
    passages with more and rarer terms higher). ``None`` when nothing is left to search for."""
    terms = query_terms(text)
    return " OR ".join(f'"{t}"' for t in terms) if terms else None


def _like(value: str) -> str:
    return "%" + value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _doc_filter(filters: SearchFilters) -> tuple[str, list[Any]]:
    """SQL over ``documents d`` for the filters (always valid; ``1`` when there are none)."""
    clauses: list[str] = []
    params: list[Any] = []
    if filters.date_from:
        clauses.append("d.date >= ?")
        params.append(filters.date_from)
    if filters.date_to:
        clauses.append("d.date <= ?")
        params.append(filters.date_to)
    if filters.kinds:
        clauses.append(f"d.kind IN ({','.join('?' * len(filters.kinds))})")
        params += list(filters.kinds)
    if filters.mm3_ids:
        clauses.append(f"d.mm3_id IN ({','.join('?' * len(filters.mm3_ids))})")
        params += list(filters.mm3_ids)
    people = [p.strip().casefold() for p in filters.people if p.strip()]
    if people:
        # A person filter applies to the meeting: its note lists them or its transcript has them.
        likes = " OR ".join("x.people LIKE ? ESCAPE '\\'" for _ in people)
        clauses.append(f"d.mm3_id IN (SELECT x.mm3_id FROM documents x WHERE {likes})")  # noqa: S608
        params += [_like(p) for p in people]
    return (" AND ".join(clauses) or "1"), params


# -- snippets --------------------------------------------------------------------------------


def passage_body(text: str) -> str:
    """The passage without the title line and the heading/speakers lines that follow it."""
    lines = text.split("\n")
    i = 1
    while i < len(lines) and i <= 3 and _HEAD_RE.match(lines[i]):
        i += 1
    return "\n".join(lines[i:]).strip()


def _stem(term: str) -> str:
    return term if len(term) <= 4 else term[: max(4, len(term) - 2)]


def make_snippet(body: str, terms: Sequence[str]) -> tuple[tuple[str, bool], ...]:
    """About 280 characters of ``body`` around the first matched term, as (text, matched)
    pieces. Matching is by word start (a rough stand-in for the index's stemming)."""
    flat = " ".join(body.split())
    pattern = (
        re.compile(r"\b(?:" + "|".join(re.escape(_stem(t)) for t in terms) + r")\w*", re.I)
        if terms
        else None
    )
    first = pattern.search(flat) if pattern else None
    start = 0
    if first and first.start() > SNIPPET_CHARS // 3:
        start = flat.rfind(" ", 0, first.start() - SNIPPET_CHARS // 3) + 1
    end = min(len(flat), start + SNIPPET_CHARS)
    if end < len(flat):
        end = max(flat.rfind(" ", start, end), start + SNIPPET_CHARS // 2)
    window = flat[start:end]
    pieces: list[tuple[str, bool]] = []
    if start > 0:
        pieces.append(("… ", False))
    pos = 0
    for m in pattern.finditer(window) if pattern else ():
        if m.start() > pos:
            pieces.append((window[pos : m.start()], False))
        pieces.append((m.group(0), True))
        pos = m.end()
    if pos < len(window):
        pieces.append((window[pos:], False))
    if end < len(flat):
        pieces.append((" …", False))
    return tuple(pieces)


# -- the searcher ----------------------------------------------------------------------------


@dataclass
class _VectorCache:
    key: tuple[int, int, str] | None = None
    items: list[tuple[int, int, array[float]]] = field(default_factory=list)


def _unit(vec: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def rrf(ranked: Sequence[Sequence[int]], k: int = RRF_K) -> dict[int, float]:
    """Reciprocal-rank fusion: each list adds ``1 / (k + rank)`` (rank from 1) per item."""
    scores: dict[int, float] = {}
    for items in ranked:
        for rank, item in enumerate(items, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return scores


class Searcher:
    def __init__(
        self, store: SearchStore, embedder: Callable[[], EmbedderChoice] | None = None
    ) -> None:
        self.store = store
        self.embedder = embedder
        self._cache = _VectorCache()

    # -- word search -------------------------------------------------------------------------

    def word_search(self, match: str, filters: SearchFilters, n: int) -> list[tuple[int, float]]:
        where, params = _doc_filter(filters)
        try:
            rows = self.store.fetchall(
                f"SELECT p.id, bm25(passages_fts, 1.0, {HEAD_WEIGHT}) AS score FROM passages_fts "  # noqa: S608
                "JOIN passages p ON p.id = passages_fts.rowid "
                "JOIN documents d ON d.id = p.doc_id "
                f"WHERE passages_fts MATCH ? AND {where} ORDER BY score LIMIT ?",
                [match, *params, n],
            )
        except sqlite3.OperationalError as exc:  # never from user text (it is quoted); defensive
            log.warning("Word search failed: %s", exc)
            return []
        found = [(int(r["id"]), float(r["score"])) for r in rows]
        if found and found[0][1] < 0:  # SQLite's bm25 is negative; more negative is better
            floor = found[0][1] * WORD_FRACTION
            found = [(pid, score) for pid, score in found if score <= floor]
        return found

    # -- vector search -----------------------------------------------------------------------

    def _vectors(self, model_id: str) -> list[tuple[int, int, array[float]]]:
        row = self.store.fetchone("PRAGMA data_version")
        key = (self.store.generation, int(row[0]) if row else 0, model_id)
        if self._cache.key != key:
            self._cache.items = [
                (pid, doc_id, unpack(blob)) for pid, doc_id, blob in self.store.vectors(model_id)
            ]
            self._cache.key = key
        return self._cache.items

    def allowed_docs(self, filters: SearchFilters) -> set[int] | None:
        where, params = _doc_filter(filters)
        if where == "1":
            return None
        rows = self.store.fetchall(f"SELECT d.id FROM documents d WHERE {where}", params)  # noqa: S608
        return {int(r["id"]) for r in rows}

    def vector_search(
        self,
        query_vec: Sequence[float],
        model_id: str,
        filters: SearchFilters,
        n: int,
        margin: float | None = VECTOR_MARGIN,
    ) -> list[tuple[int, float]]:
        items = self._vectors(model_id)
        allowed = self.allowed_docs(filters)
        q = array("f", _unit(query_vec))
        dims = len(q)
        scored = (
            (pid, sum(map(operator.mul, q, vec)))
            for pid, doc_id, vec in items
            if len(vec) == dims and (allowed is None or doc_id in allowed)
        )
        best = heapq.nlargest(n, scored, key=lambda t: t[1])
        if best and margin is not None:
            floor = best[0][1] - margin
            best = [(pid, score) for pid, score in best if score >= floor]
        return best

    # -- both --------------------------------------------------------------------------------

    def _load_hits(
        self,
        scores: dict[int, float],
        words: dict[int, tuple[int, float]],
        vectors: dict[int, tuple[int, float]],
        terms: Sequence[str],
        limit: int,
    ) -> list[Hit]:
        best = heapq.nlargest(limit, scores.items(), key=lambda t: t[1])
        if not best:
            return []
        ids = [pid for pid, _ in best]
        marks = ",".join("?" * len(ids))
        rows = self.store.fetchall(
            "SELECT p.id, p.text, p.body, p.heading, p.section_id, p.start_s, p.end_s, p.speakers, "  # noqa: S608
            "d.mm3_id, d.kind, d.path, d.title, d.date, "
            "(SELECT n.path FROM documents n WHERE n.mm3_id = d.mm3_id AND n.kind = 'note' "
            " ORDER BY n.id LIMIT 1) AS note_path, "
            "(SELECT n.title FROM documents n WHERE n.mm3_id = d.mm3_id AND n.kind = 'note' "
            " ORDER BY n.id LIMIT 1) AS note_title "
            f"FROM passages p JOIN documents d ON d.id = p.doc_id WHERE p.id IN ({marks})",
            ids,
        )
        by_id = {int(r["id"]): r for r in rows}
        hits = []
        for pid, score in best:
            r = by_id.get(pid)
            if r is None:  # removed by a concurrent update
                continue
            body = r["body"] or passage_body(r["text"])
            w, v = words.get(pid), vectors.get(pid)
            hits.append(
                Hit(
                    passage_id=pid,
                    mm3_id=r["mm3_id"],
                    kind=r["kind"],
                    path=r["path"],
                    note_path=r["note_path"],
                    title=r["note_title"] or r["title"],
                    date=r["date"],
                    text=r["text"],
                    body=body,
                    heading=r["heading"],
                    section_id=r["section_id"],
                    start_s=r["start_s"],
                    end_s=r["end_s"],
                    speakers=tuple(json.loads(r["speakers"])),
                    score=score,
                    word_rank=w[0] if w else None,
                    word_score=w[1] if w else None,
                    vector_rank=v[0] if v else None,
                    vector_score=v[1] if v else None,
                    snippet=make_snippet(body, terms),
                )
            )
        return hits

    async def query(
        self,
        text: str,
        *,
        limit: int = 20,
        filters: SearchFilters | None = None,
        candidates: int | None = None,
        use_vectors: bool = True,
        vector_margin: float | None = VECTOR_MARGIN,
    ) -> SearchResult:
        """The passages most related to ``text``, by meaning and by words.

        ``limit`` passages are returned (best first); each list contributes ``candidates``
        (default ``max(3 * limit, 50)``) to the fusion; vector candidates must also be within
        ``vector_margin`` of the best similarity (``None``: no cut-off). Never raises for the
        user's text; an embedder failure falls back to words only, with the reason."""
        filters = filters or SearchFilters()
        text = text.strip()[:MAX_QUERY_CHARS]
        n = candidates or max(3 * limit, 50)
        timings: dict[str, float] = {}
        terms = query_terms(text)
        match = fts_query(text)
        words: list[tuple[int, float]] = []
        if match:
            started = time.perf_counter()
            words = await asyncio.to_thread(self.word_search, match, filters, n)
            timings["words"] = (time.perf_counter() - started) * 1000
        vectors: list[tuple[int, float]] = []
        reason: str | None = None
        badge: str | None = None
        vectors_used = False
        if not text:
            reason = "Type something to search for."
        elif not use_vectors or self.embedder is None:
            reason = "Meaning search is switched off."
        else:
            try:
                choice = self.embedder()
                badge = choice.badge
                choice.require_consent()
                stored = await asyncio.to_thread(
                    self.store.fetchone,
                    "SELECT COUNT(*) AS n FROM vectors WHERE model = ?",
                    (choice.model_id,),
                )
                if not stored or not stored["n"]:
                    reason = (
                        "The index has no meaning vectors yet (it is still being built, or the "
                        "embedding model is not available); see Settings → Search & Ask."
                    )
                else:
                    started = time.perf_counter()
                    qvec = await choice.embed_query(text)
                    timings["embed_query"] = (time.perf_counter() - started) * 1000
                    started = time.perf_counter()
                    vectors = await asyncio.to_thread(
                        self.vector_search, qvec, choice.model_id, filters, n, vector_margin
                    )
                    timings["vectors"] = (time.perf_counter() - started) * 1000
                    vectors_used = True
            except MM3Error as exc:
                reason = f"{exc.message} {exc.hint}".strip()
        scores = rrf([[pid for pid, _ in words], [pid for pid, _ in vectors]])
        word_info = {pid: (rank, s) for rank, (pid, s) in enumerate(words, start=1)}
        vector_info = {pid: (rank, s) for rank, (pid, s) in enumerate(vectors, start=1)}
        hits = await asyncio.to_thread(
            self._load_hits, scores, word_info, vector_info, terms, limit
        )
        modes: dict[tuple[bool, bool], Mode] = {
            (True, True): "hybrid",
            (True, False): "meaning",
            (False, True): "words",
            (False, False): "none",
        }
        mode = modes[(vectors_used, bool(match))]
        if mode == "none" and text and reason is None:
            reason = "The search has no words to look for."
        return SearchResult(
            query=text,
            hits=hits,
            mode=mode,
            reason=None if vectors_used else reason,
            embedder=badge,
            timings_ms=timings,
        )

    # -- facts -------------------------------------------------------------------------------

    def meeting_facts(
        self, mm3_ids: Sequence[str], hits: Iterable[Hit] = ()
    ) -> dict[str, MeetingFacts]:
        """Title, date, participants and speakers of each meeting, from the index (which mirrors
        the files' frontmatter and data blocks). Unknown ids are left out."""
        in_hits: dict[str, list[str]] = {}
        for hit in hits:
            names = in_hits.setdefault(hit.mm3_id, [])
            names += [s for s in hit.speakers if s not in names]
        facts: dict[str, MeetingFacts] = {}
        docs = self.store.documents_for(list(dict.fromkeys(mm3_ids)))
        for mm3_id in dict.fromkeys(mm3_ids):
            mine = [d for d in docs if d.mm3_id == mm3_id]
            if not mine:
                continue
            note = next((d for d in mine if d.kind == "note"), None)
            transcript = next((d for d in mine if d.kind == "transcript"), None)
            first = note or mine[0]
            speakers = tuple(
                dict.fromkeys(
                    (*(transcript.speakers if transcript else ()), *(note.speakers if note else ()))
                )
            )
            facts[mm3_id] = MeetingFacts(
                mm3_id=mm3_id,
                title=first.title,
                date=first.date,
                participants=note.participants if note else (),
                speakers=speakers,
                speakers_in_hits=tuple(
                    s for s in in_hits.get(mm3_id, []) if not PLACEHOLDER_RE.match(s)
                ),
                note_path=note.path if note else None,
                transcript_path=transcript.path if transcript else None,
            )
        return facts
