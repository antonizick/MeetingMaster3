"""Live checks against the Ollama on the reference machine. Run with ``-m network``."""

from __future__ import annotations

import pytest

from meetingmaster3.llm.base import GenerateRequest
from meetingmaster3.llm.ollama import OllamaBackend

pytestmark = pytest.mark.network
MODEL = "qwen3:1.7b"


async def _backend() -> OllamaBackend:
    b = OllamaBackend("ollama")
    status = await b.test_connection()
    if not status.ok or MODEL not in {m.id for m in await b.list_models()}:
        pytest.skip(f"Ollama with {MODEL} not available")
    return b


async def test_generate_and_stream_live() -> None:
    b = await _backend()
    req = GenerateRequest(
        model=MODEL,
        prompt="Reply with the single word: pong",
        max_tokens=200,
        temperature=0,
        think=False,
    )
    result = await b.generate(req)
    assert result.text.strip() and result.latency_ms > 0
    pieces = [p async for p in b.stream(req)]
    assert "".join(pieces).strip()


async def test_context_window_and_unload_live() -> None:
    b = await _backend()
    await b.warm(MODEL)
    assert (b.context_window(MODEL) or 0) >= 2048
    await b.unload_all()
    assert await b.running_models() == []
