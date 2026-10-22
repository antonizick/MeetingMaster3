"""Ollama backend: ``/api/chat``, ``/api/embed``, ``/api/tags``, ``/api/show`` and ``/api/ps``."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any

import httpx

from meetingmaster3.errors import MM3Error
from meetingmaster3.llm._http import MAX_ATTEMPTS, error_from_exception, error_from_response, send
from meetingmaster3.llm.base import (
    E_LLM_BAD_RESPONSE,
    E_LLM_CONFIG,
    E_LLM_CONTEXT,
    ConnectionStatus,
    EmbedPurpose,
    GenerateRequest,
    GenerateResult,
    ModelInfo,
    Usage,
    check_vectors,
    connection_failure,
    embed_unsupported,
    is_local_url,
    llm_error,
)
from meetingmaster3.llm.budget import estimate_tokens

log = logging.getLogger(__name__)

PROVIDER = "Ollama"
DEFAULT_BASE_URL = "http://127.0.0.1:11434"
MIN_NUM_CTX = 4096
DEFAULT_OUTPUT_RESERVE = 2048
PROBE_TIMEOUT_S = 10.0
EMBED_BATCH = 32
"""Texts per ``/api/embed`` call."""
EMBED_TIMEOUT_S = 120.0
EMBED_KEEP_ALIVE = "30s"
"""How long the embedding model stays loaded after a call: long enough for the next batch, short
enough that it has left the GPU before a transcription would want it (R5)."""


class OllamaBackend:
    kind = "ollama"
    supports_embeddings = True

    def __init__(
        self,
        id: str = "ollama",
        base_url: str = DEFAULT_BASE_URL,
        default_model: str | None = None,
        params: Mapping[str, Any] | None = None,
        api_key: str | None = None,
        headers: Mapping[str, str] | None = None,
        context_window: int | None = None,
    ) -> None:
        self.id = id
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self.params = dict(params or {})
        self.is_local = is_local_url(self.base_url)
        self._headers = dict(headers or {})
        if api_key:
            self._headers["Authorization"] = f"Bearer {api_key}"
        self._override_ctx = context_window
        self._ctx: dict[str, int] = {}
        self._caps: dict[str, frozenset[str]] = {}

    # -- plumbing ----------------------------------------------------------------------

    def _client(self, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.base_url, headers=self._headers, timeout=timeout)

    async def _call(
        self,
        method: str,
        path: str,
        *,
        timeout: float,
        body: dict[str, Any] | None = None,
        attempts: int = MAX_ATTEMPTS,
    ) -> httpx.Response:
        async with self._client(timeout) as client:
            request = client.build_request(method, path, json=body)
            return await send(client, request, PROVIDER, attempts=attempts)

    def _payload(self, req: GenerateRequest, stream: bool) -> dict[str, Any]:
        messages = [{"role": m.role, "content": m.content} for m in req.chat()]
        if system := req.system_text():
            messages.insert(0, {"role": "system", "content": system})
        options: dict[str, Any] = {**self.params, "temperature": req.temperature}
        if req.max_tokens:
            options["num_predict"] = req.max_tokens
        if req.stop:
            options["stop"] = list(req.stop)
        options["num_ctx"] = self._num_ctx(req, options.get("num_ctx"))
        body: dict[str, Any] = {
            "model": req.model,
            "messages": messages,
            "stream": stream,
            "options": options,
        }
        if req.json_mode:
            body["format"] = "json"
        if req.think is not None:
            body["think"] = req.think
        return body

    def _num_ctx(self, req: GenerateRequest, configured: Any) -> int:
        """Ollama's default window (about 4k) silently truncates long prompts, so size it."""
        if req.num_ctx:
            wanted = req.num_ctx
        elif configured:
            wanted = int(configured)
        else:
            need = estimate_tokens(req.full_text()) + (req.max_tokens or DEFAULT_OUTPUT_RESERVE)
            wanted = max(MIN_NUM_CTX, -(-need // 1024) * 1024)
        ceiling = self.context_window(req.model)
        return min(wanted, ceiling) if ceiling else wanted

    # -- LLMBackend --------------------------------------------------------------------

    async def generate(self, req: GenerateRequest) -> GenerateResult:
        started = time.monotonic()
        resp = await self._call(
            "POST", "/api/chat", timeout=req.timeout, body=self._payload(req, False)
        )
        try:
            data = resp.json()
            text = data["message"]["content"]
        except (ValueError, KeyError, TypeError) as exc:
            raise llm_error(E_LLM_BAD_RESPONSE, "Ollama returned an unexpected response.") from exc
        return GenerateResult(
            text=text,
            model=data.get("model", req.model),
            usage=Usage(data.get("prompt_eval_count"), data.get("eval_count")),
            finish_reason=data.get("done_reason"),
            latency_ms=int((time.monotonic() - started) * 1000),
        )

    async def stream(self, req: GenerateRequest) -> AsyncIterator[str]:
        async with self._client(req.timeout) as client:
            request = client.build_request("POST", "/api/chat", json=self._payload(req, True))
            resp = await send(client, request, PROVIDER, stream=True)
            try:
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        event = json.loads(line)
                    except ValueError as exc:
                        raise llm_error(
                            E_LLM_BAD_RESPONSE, "Ollama sent a malformed stream."
                        ) from exc
                    if err := event.get("error"):
                        raise self._stream_error(str(err))
                    if piece := event.get("message", {}).get("content"):
                        yield piece
                    if event.get("done"):
                        return
            except httpx.HTTPError as exc:
                raise error_from_exception(PROVIDER, exc) from exc
            finally:
                await resp.aclose()

    @staticmethod
    def _stream_error(text: str) -> MM3Error:
        fake = httpx.Response(400, text=text)
        err = error_from_response(PROVIDER, fake, text)
        return (
            err
            if err.code == E_LLM_CONTEXT
            else llm_error(E_LLM_BAD_RESPONSE, f"Ollama: {text[:200]}")
        )

    async def list_models(self) -> list[ModelInfo]:
        """Installed models, with each one's context window and whether it can write text."""
        names = [m.id for m in await self._list_models()]
        await asyncio.gather(*(self.warm(n) for n in names))
        return await self._list_models()

    async def _list_models(self, attempts: int = MAX_ATTEMPTS) -> list[ModelInfo]:
        resp = await self._call("GET", "/api/tags", timeout=PROBE_TIMEOUT_S, attempts=attempts)
        try:
            items = resp.json().get("models", [])
            return [
                ModelInfo(
                    id=m["name"],
                    name=m["name"],
                    size_bytes=m.get("size"),
                    context_window=self._ctx.get(m["name"]),
                    can_generate=self.can_generate(m["name"]),
                )
                for m in items
            ]
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise llm_error(
                E_LLM_BAD_RESPONSE, "Ollama returned an unexpected model list."
            ) from exc

    async def test_connection(self) -> ConnectionStatus:
        started = time.monotonic()
        try:
            models = await self._list_models(attempts=1)
        except MM3Error as exc:
            return connection_failure(exc)
        latency = int((time.monotonic() - started) * 1000)
        present = None
        message = f"Connected to Ollama at {self.base_url}; {len(models)} model(s) installed."
        hint = ""
        if self.default_model:
            names = {m.id for m in models}
            present = self.default_model in names or f"{self.default_model}:latest" in names
            if not present:
                hint = f"Run `ollama pull {self.default_model}`."
                message += f" Model {self.default_model!r} is not installed."
        return ConnectionStatus(
            ok=True,
            message=message,
            latency_ms=latency,
            hint=hint,
            models=len(models),
            default_model_present=present,
            details={"location": "local" if self.is_local else "remote"},
        )

    def context_window(self, model: str) -> int | None:
        return self._override_ctx or self._ctx.get(model)

    def can_generate(self, model: str) -> bool | None:
        """False for an embedding-only model (Ollama lists its capabilities); None if unknown."""
        caps = self._caps.get(model)
        return None if caps is None else "completion" in caps

    async def warm(self, model: str) -> None:
        """Read the model's maximum context length and capabilities from ``/api/show``."""
        if model in self._ctx or model in self._caps:
            return
        try:
            resp = await self._call(
                "POST", "/api/show", timeout=PROBE_TIMEOUT_S, body={"model": model}
            )
            data = resp.json()
            info = data.get("model_info") or {}
        except (MM3Error, ValueError, AttributeError):
            return
        if not isinstance(info, dict):
            info = {}
        caps = data.get("capabilities")
        if isinstance(caps, list):  # older Ollama versions do not report them
            self._caps[model] = frozenset(str(c) for c in caps)
        for key, value in info.items():
            if key.endswith(".context_length") and isinstance(value, int):
                self._ctx[model] = value
                return

    # -- embeddings (Phase 15i) ------------------------------------------------------------

    async def embed(
        self, model: str, texts: Sequence[str], *, purpose: EmbedPurpose = "document"
    ) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), EMBED_BATCH):
            batch = list(texts[start : start + EMBED_BATCH])
            body = {"model": model, "input": batch, "keep_alive": EMBED_KEEP_ALIVE}
            try:
                resp = await self._call("POST", "/api/embed", timeout=EMBED_TIMEOUT_S, body=body)
            except MM3Error as exc:
                raise self._embed_error(model, exc) from exc
            try:
                data = resp.json()["embeddings"]
            except (ValueError, KeyError, TypeError) as exc:
                raise llm_error(
                    E_LLM_BAD_RESPONSE, "Ollama returned an unexpected answer."
                ) from exc
            vectors += check_vectors(PROVIDER, data, len(batch))
        return vectors

    @staticmethod
    def _embed_error(model: str, exc: MM3Error) -> MM3Error:
        reason = str(exc.details.get("provider_reason", "")).lower()
        if "not found" in reason or "pull" in reason:
            return llm_error(
                E_LLM_CONFIG,
                f"The embedding model {model!r} is not installed in Ollama.",
                f"Run `ollama pull {model}`.",
                status_code=400,
            )
        if "does not support" in reason:
            return embed_unsupported(f"Ollama model {model!r}")
        return exc

    async def list_embedding_models(self) -> list[ModelInfo]:
        """Installed models whose ``/api/show`` capabilities include ``embedding``."""
        models = await self.list_models()
        return [m for m in models if "embedding" in self._caps.get(m.id, frozenset())]

    # -- Ollama-specific helpers ---------------------------------------------------------

    async def running_models(self) -> list[str]:
        resp = await self._call("GET", "/api/ps", timeout=PROBE_TIMEOUT_S)
        return [m["name"] for m in resp.json().get("models", [])]

    async def unload_all(self, wait_s: float = 10.0) -> list[str]:
        """Ask Ollama to evict every loaded model (``keep_alive: 0``) to free VRAM (R5).

        Eviction is asynchronous on Ollama's side, so this waits (up to ``wait_s``) until
        ``/api/ps`` is empty before returning; Phase 06 relies on the VRAM being free.
        """
        unloaded = []
        for name in await self.running_models():
            await self._call(
                "POST",
                "/api/generate",
                timeout=PROBE_TIMEOUT_S,
                body={"model": name, "keep_alive": 0},
            )
            unloaded.append(name)
        deadline = time.monotonic() + wait_s
        while unloaded and await self.running_models() and time.monotonic() < deadline:
            await asyncio.sleep(0.25)
        return unloaded
