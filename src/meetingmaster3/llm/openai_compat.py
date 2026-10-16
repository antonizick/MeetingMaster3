"""OpenAI-compatible chat completions over plain httpx (OpenRouter, OpenAI, LM Studio, vLLM...)."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator, Mapping
from typing import Any

import httpx

from meetingmaster3.errors import MM3Error
from meetingmaster3.llm._http import MAX_ATTEMPTS, error_from_exception, send
from meetingmaster3.llm.base import (
    E_LLM_BAD_RESPONSE,
    ConnectionStatus,
    GenerateRequest,
    GenerateResult,
    ModelInfo,
    Usage,
    check_answer,
    connection_failure,
    is_local_url,
    llm_error,
)

log = logging.getLogger(__name__)

PRESET_BASE_URLS = {
    "openrouter": "https://openrouter.ai/api/v1",
    "openai": "https://api.openai.com/v1",
}
PROBE_TIMEOUT_S = 10.0
REASONING_LOW: dict[str, Any] = {"effort": "low"}
"""OpenRouter's reasoning setting for a model that refuses ``{"enabled": false}`` ("Reasoning is
mandatory for this endpoint", Claude Sonnet 5.5 and Opus 5.5), learned per model (ADR-0045)."""
REASONING_ROOM = 4096
"""Output tokens added to ``max_tokens`` when the model must reason: reasoning counts against
``max_tokens``. Only the tokens used are billed."""


class OpenAICompatBackend:
    kind = "openai_compat"

    def __init__(
        self,
        id: str,
        base_url: str,
        api_key: str | None = None,
        default_model: str | None = None,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        context_window: int | None = None,
        kind: str = "openai_compat",
    ) -> None:
        self.id = id
        self.kind = kind
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self.params = dict(params or {})
        self.is_local = is_local_url(self.base_url)
        self._headers = dict(headers or {})
        if api_key:
            self._headers["Authorization"] = f"Bearer {api_key}"
        self._override_ctx = context_window
        self._ctx: dict[str, int] = {}
        self._reasoning: dict[str, dict[str, Any]] = {}
        """Per model, the ``reasoning`` setting used instead of ``{"enabled": false}``."""
        self._provider = {"openrouter": "OpenRouter", "openai": "OpenAI"}.get(kind, "the server")

    def _client(self, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.base_url, headers=self._headers, timeout=timeout)

    def _payload(self, req: GenerateRequest, stream: bool) -> dict[str, Any]:
        messages = [{"role": m.role, "content": m.content} for m in req.chat()]
        if system := req.system_text():
            messages.insert(0, {"role": "system", "content": system})
        body: dict[str, Any] = {
            **self.params,
            "model": req.model,
            "messages": messages,
            "temperature": req.temperature,
            "stream": stream,
        }
        if req.max_tokens:
            body["max_tokens"] = req.max_tokens
        if req.stop:
            body["stop"] = list(req.stop)
        if req.json_mode:
            body["response_format"] = {"type": "json_object"}
        if self._sends_reasoning(req):
            # OpenRouter's unified switch. Claude 5.x thinks by default there and spends the
            # section's max_tokens on hidden reasoning (measured on Haiku 5.5, Phase 15g).
            learned = self._reasoning.get(req.model) if req.think is False else None
            body["reasoning"] = learned or {"enabled": req.think}
            if learned and req.max_tokens:
                body["max_tokens"] = req.max_tokens + REASONING_ROOM
        return body

    def _sends_reasoning(self, req: GenerateRequest) -> bool:
        return (
            self.kind == "openrouter" and req.think is not None and "reasoning" not in self.params
        )

    def _adapt(self, req: GenerateRequest, exc: MM3Error) -> bool:
        """Learn the model's reasoning setting when it refuses to turn reasoning off."""
        reason = str(exc.details.get("provider_reason", "")).lower()
        if (
            req.think is not False
            or not self._sends_reasoning(req)
            or req.model in self._reasoning
            or "reasoning is mandatory" not in reason
        ):
            return False
        log.info(
            "%s model %s cannot turn reasoning off; using low effort", self._provider, req.model
        )
        self._reasoning[req.model] = REASONING_LOW
        return True

    async def _send(
        self, client: httpx.AsyncClient, req: GenerateRequest, stream: bool
    ) -> httpx.Response:
        """Send the request; repeat it once if the model refuses the reasoning switch. The
        refused call is not billed."""
        while True:
            request = client.build_request(
                "POST", "/chat/completions", json=self._payload(req, stream)
            )
            try:
                return await send(client, request, self._provider, stream=stream)
            except MM3Error as exc:
                if not self._adapt(req, exc):
                    raise

    async def generate(self, req: GenerateRequest) -> GenerateResult:
        started = time.monotonic()
        async with self._client(req.timeout) as client:
            resp = await self._send(client, req, False)
        try:
            data = resp.json()
            choice = data["choices"][0]
            text = choice["message"]["content"] or ""
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise llm_error(
                E_LLM_BAD_RESPONSE, f"Unexpected response from {self._provider}."
            ) from exc
        usage = data.get("usage") or {}
        finish = choice.get("finish_reason")
        check_answer(self._provider, text, finish)
        return GenerateResult(
            text=text,
            model=data.get("model", req.model),
            usage=Usage(usage.get("prompt_tokens"), usage.get("completion_tokens")),
            finish_reason=finish,
            latency_ms=int((time.monotonic() - started) * 1000),
        )

    async def stream(self, req: GenerateRequest) -> AsyncIterator[str]:
        async with self._client(req.timeout) as client:
            resp = await self._send(client, req, True)
            streamed = False
            finish: str | None = None
            try:
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue  # blank separators and ": keep-alive" comments
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        event = json.loads(payload)
                    except ValueError as exc:
                        raise llm_error(E_LLM_BAD_RESPONSE, "Malformed event stream.") from exc
                    if event.get("error"):
                        raise llm_error(
                            E_LLM_BAD_RESPONSE, f"{self._provider} reported an error mid-stream."
                        )
                    for choice in event.get("choices", []):
                        finish = choice.get("finish_reason") or finish
                        if piece := (choice.get("delta") or {}).get("content"):
                            streamed = streamed or bool(piece.strip())
                            yield piece
                check_answer(self._provider, "x" if streamed else "", finish)
            except httpx.HTTPError as exc:
                raise error_from_exception(self._provider, exc) from exc
            finally:
                await resp.aclose()

    async def list_models(self) -> list[ModelInfo]:
        return await self._list_models()

    async def _list_models(self, attempts: int = MAX_ATTEMPTS) -> list[ModelInfo]:
        async with self._client(PROBE_TIMEOUT_S) as client:
            request = client.build_request("GET", "/models")
            resp = await send(client, request, self._provider, attempts=attempts)
        try:
            items = resp.json()["data"]
            models = [
                ModelInfo(
                    id=m["id"],
                    name=m.get("name"),
                    context_window=m.get("context_length") or m.get("context_window"),
                )
                for m in items
            ]
        except (ValueError, KeyError, TypeError) as exc:
            raise llm_error(
                E_LLM_BAD_RESPONSE, f"Unexpected model list from {self._provider}."
            ) from exc
        for m in models:
            if m.context_window:
                self._ctx[m.id] = m.context_window
        return models

    async def test_connection(self) -> ConnectionStatus:
        started = time.monotonic()
        try:
            models = await self._list_models(attempts=1)
        except MM3Error as exc:
            return connection_failure(exc)
        latency = int((time.monotonic() - started) * 1000)
        present = None
        message = f"Connected to {self.base_url}; {len(models)} model(s) listed."
        hint = ""
        if self.default_model:
            present = self.default_model in {m.id for m in models}
            if not present:
                message += f" Model {self.default_model!r} was not in the list."
                hint = "Check the model id (some servers only list a subset)."
        return ConnectionStatus(
            ok=True,
            message=message,
            latency_ms=latency,
            hint=hint,
            models=len(models),
            default_model_present=present,
            details={"location": "local" if self.is_local else "cloud"},
        )

    def context_window(self, model: str) -> int | None:
        return self._override_ctx or self._ctx.get(model)

    async def warm(self, model: str) -> None:
        if model in self._ctx:
            return
        try:
            await self.list_models()
        except MM3Error:
            return
