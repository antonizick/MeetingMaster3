"""A deterministic, offline LLM backend for tests and ``MM3_FAKE_PIPELINE=1``.

Without a ``responder`` it answers from the prompt itself: section requests get a short body
built from the transcript lines (sentences with "will" or "I'll" become tasks for their speaker,
sentences with "agree", "decide" or "let's" become decisions), and JSON requests get a valid
map-reduce extraction. Tests pass a ``responder`` to script exact answers (including bad JSON).
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field

from meetingmaster3.llm.base import (
    ConnectionStatus,
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
    return (
        f"Simulated {title.lower()} from the offline fake model: {len(lines)} turns by "
        f"{', '.join(speakers) or 'nobody'}."
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

    async def generate(self, req: GenerateRequest) -> GenerateResult:
        self.calls.append(req)
        if self.responder is not None:
            text = self.responder(req)
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
        return [ModelInfo(id=m, context_window=self.window) for m in self.models]

    async def test_connection(self) -> ConnectionStatus:
        return ConnectionStatus(ok=True, message="Fake backend (offline)", models=len(self.models))

    def context_window(self, model: str) -> int | None:
        return self.window

    async def warm(self, model: str) -> None:
        return None
