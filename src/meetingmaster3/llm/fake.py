"""A deterministic, offline LLM backend for tests and ``MM3_FAKE_PIPELINE=1``.

Without a ``responder`` it answers from the prompt itself: section requests get a short body
built from the transcript lines (sentences with "will" or "I'll" become tasks for their speaker,
sentences with "agree", "decide" or "let's" become decisions), and JSON requests get a valid
map-reduce extraction. Tests pass a ``responder`` to script exact answers (including bad JSON).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, field

from meetingmaster3.llm.base import (
    ConnectionStatus,
    EmbedPurpose,
    GenerateRequest,
    GenerateResult,
    ModelInfo,
    Usage,
)
from meetingmaster3.llm.budget import estimate_tokens

Responder = Callable[[GenerateRequest], str]

_LINE_RE = re.compile(r"^\[(?P<time>[\d:]+)\] (?P<speaker>[^:\n]{1,80}): (?P<text>.+)$", re.M)
_SECTION_RE = re.compile(r'Now write the section "(?P<title>[^"]+)"')
_ACTION_RE = re.compile(r"\b(I'll|I will|will|going to)\b", re.I)
_DECISION_RE = re.compile(r"\b(agree|agreed|decide|decided|let's|we'll go with)\b", re.I)


def _lines(prompt: str) -> list[tuple[str, str, str]]:
    if "<transcript>" in prompt:  # ignore candidate lists and other quoted material
        prompt = prompt.split("<transcript>", 1)[1].split("</transcript>", 1)[0]
    return [(m["time"], m["speaker"].strip(), m["text"].strip()) for m in _LINE_RE.finditer(prompt)]


def _extraction(prompt: str) -> str:
    lines = _lines(prompt)
    data = {
        "summary": f"This part has {len(lines)} turns."
        + (f" It starts with {lines[0][1]}." if lines else ""),
        "points": [{"text": t, "speaker": s, "time": tm} for tm, s, t in lines[:3]],
        "decisions": [
            {"text": t, "rationale": "", "by": s, "time": tm}
            for tm, s, t in lines
            if _DECISION_RE.search(t)
        ],
        "actions": [
            {"task": t, "owner": s, "due": "not stated", "time": tm}
            for tm, s, t in lines
            if _ACTION_RE.search(t)
        ],
        "questions": [
            {"text": t, "raised_by": s, "time": tm} for tm, s, t in lines if t.endswith("?")
        ],
    }
    return json.dumps(data)


def _section(prompt: str) -> str:
    m = _SECTION_RE.search(prompt)
    title = m["title"] if m else "Notes"
    lines = _lines(prompt)
    low = title.lower()
    if "action" in low:
        tasks = [(tm, s, t) for tm, s, t in lines if _ACTION_RE.search(t)]
        return (
            "\n".join(f"- [ ] **{s}:** {t} (due: not stated) [{tm}]" for tm, s, t in tasks)
            or "No action items were agreed."
        )
    if "decision" in low:
        found = [(tm, s, t) for tm, s, t in lines if _DECISION_RE.search(t)]
        return (
            "\n".join(f"- **{t}** ({s}) [{tm}]" for tm, s, t in found) or "No decisions were made."
        )
    if "question" in low:
        found = [(tm, s, t) for tm, s, t in lines if t.endswith("?")]
        return "\n".join(f"- {t} (raised by {s}) [{tm}]" for tm, s, t in found) or (
            "No open questions."
        )
    speakers = list(dict.fromkeys(s for _, s, _ in lines))
    text = (
        f"Simulated {title.lower()} from the offline fake model: {len(lines)} turns by "
        f"{', '.join(speakers) or 'nobody'}."
    )
    if "detailed" in low:  # Summary Detailed needs two paragraphs or more (R25)
        first = lines[0][2] if lines else "nothing"
        text += f"\n\nThe conversation opened with: {first}"
    return text


FAKE_DIMENSIONS = 64


def _words(text: str) -> frozenset[str]:
    return frozenset(text.split())


_CONCEPTS: tuple[frozenset[str], ...] = (
    _words(
        "budget budgets overrun overran overspend overspent spending spend spent cost costs "
        "exceeded exceed forecast forecasts planned money expensive price dollars"
    ),
    _words("hire hiring hired recruit recruiting candidate candidates headcount"),
    _words("launch launches release releases ship shipping shipped rollout"),
    _words("bug bugs outage incident crash crashes failure failures broken"),
)
"""Toy "meanings" for :func:`fake_embedding`: words in one group land on the same dimension, so
tests can check that a search finds a topic phrased in different words."""
_WORD_RE = re.compile(r"[a-z0-9]+")


def fake_embedding(text: str, dims: int = FAKE_DIMENSIONS) -> list[float]:
    """A deterministic unit vector: one dimension per toy concept (weighted 3), the rest hashed
    words. Not a real model; good enough to rank synthetic test meetings."""
    vec = [0.0] * dims
    for word in _WORD_RE.findall(text.lower()):
        hit = next((i for i, group in enumerate(_CONCEPTS) if word in group), None)
        if hit is not None:
            vec[hit] += 3.0
            continue
        digest = hashlib.blake2b(word.encode(), digest_size=4).digest()
        vec[len(_CONCEPTS) + int.from_bytes(digest, "big") % (dims - len(_CONCEPTS))] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


ASK_MARK = "MM3 Ask agent · step: "
_SPOKEN_RE = re.compile(r"^(?P<name>[A-Z][\w.'-]*(?: [A-Z][\w.'-]*){0,3}): (?P<text>.+)$", re.M)
_CITED_RE = re.compile(r"^(\[\[[^\]]+\]\]) \((?P<date>[^,)]*)", re.M)


def _concepts(text: str) -> set[int]:
    words = set(_WORD_RE.findall(text.lower()))
    return {i for i, group in enumerate(_CONCEPTS) if words & group}


def _ask(step: str, prompt: str) -> str:
    """Answers for the Ask agent (Phase 15j): the topic is the question's toy concepts, and a
    meeting is relevant when its excerpts share one."""
    question = prompt.split("Question:\n", 1)[-1].split("\n\n", 1)[0].strip()
    if step == "plan":
        return json.dumps(
            {"topic": question[:60], "queries": [question], "wants": ["count", "people", "table"]}
        )
    if step == "read":
        excerpts = prompt.split("<meeting>", 1)[-1].split("</meeting>", 1)[0]
        topic = _concepts(question)
        spoken = [
            (m["name"], m["text"].strip())
            for m in _SPOKEN_RE.finditer(excerpts)
            if topic & _concepts(m["text"])
        ]
        if not topic or not (topic & _concepts(excerpts.split("\n\n", 1)[-1])):
            return json.dumps({"relevant": "no", "finding": "", "people": [], "quotes": []})
        people = [{"name": n, "role": "", "contribution": t[:120]} for n, t in dict(spoken).items()]
        quotes = [{"text": t, "time": None} for _, t in spoken[:2]]
        first = next((ln for ln in excerpts.splitlines() if topic & _concepts(ln)), "")
        finding = "The meeting discusses it: " + first.strip("- ").strip()[:160]
        return json.dumps(
            {"relevant": "yes", "finding": finding, "people": people, "quotes": quotes}
        )
    cited = [m.group(1) for m in _CITED_RE.finditer(prompt.split("Findings", 1)[-1])]
    return (
        f"The topic came up in {len(cited)} meeting{'' if len(cited) == 1 else 's'}: "
        + ", ".join(cited)
        + ".\n\nThis answer was written by the offline fake model."
    )


@dataclass
class FakeLLMBackend:
    """Implements :class:`~meetingmaster3.llm.base.LLMBackend` without any network."""

    id: str = "fake"
    kind: str = "fake"
    is_local: bool = True
    window: int | None = 8192
    responder: Responder | None = None
    calls: list[GenerateRequest] = field(default_factory=list)
    models: tuple[str, ...] = ("fake-model",)
    embedding_models: tuple[str, ...] = ()
    """Models that cannot write text, like Ollama's embedding models."""
    supports_embeddings: bool = True
    embed_calls: list[tuple[str, tuple[str, ...]]] = field(default_factory=list)
    """``(model, texts)`` of every :meth:`embed` call."""
    delay: float = 0.0
    """Seconds each call takes (``MM3_FAKE_LLM_SECONDS`` in the fake pipeline), so progress UI
    can be watched in the browser tests."""

    async def generate(self, req: GenerateRequest) -> GenerateResult:
        self.calls.append(req)
        if self.delay:
            await asyncio.sleep(self.delay)
        system = req.system_text() or ""
        if self.responder is not None:
            text = self.responder(req)
        elif system.startswith(ASK_MARK):
            step = system[len(ASK_MARK) :].split("\n", 1)[0].strip()
            text = _ask(step, "\n".join(m.content for m in req.chat()))
        else:
            prompt = "\n".join(m.content for m in req.chat())
            text = _extraction(prompt) if req.json_mode else _section(prompt)
        return GenerateResult(
            text=text,
            model=req.model,
            usage=Usage(estimate_tokens(req.full_text()), estimate_tokens(text)),
            finish_reason="stop",
        )

    async def stream(self, req: GenerateRequest) -> AsyncIterator[str]:
        result = await self.generate(req)
        yield result.text

    async def list_models(self) -> list[ModelInfo]:
        return [
            ModelInfo(id=m, context_window=self.window, can_generate=self.can_generate(m))
            for m in (*self.models, *self.embedding_models)
        ]

    def can_generate(self, model: str) -> bool:
        return model not in self.embedding_models

    async def embed(
        self, model: str, texts: Sequence[str], *, purpose: EmbedPurpose = "document"
    ) -> list[list[float]]:
        self.embed_calls.append((model, tuple(texts)))
        if self.delay:
            await asyncio.sleep(self.delay)
        return [fake_embedding(t) for t in texts]

    async def list_embedding_models(self) -> list[ModelInfo]:
        return [ModelInfo(id=m, can_generate=False) for m in self.embedding_models]

    async def test_connection(self) -> ConnectionStatus:
        return ConnectionStatus(ok=True, message="Fake backend (offline)", models=len(self.models))

    def context_window(self, model: str) -> int | None:
        return self.window

    async def warm(self, model: str) -> None:
        return None
