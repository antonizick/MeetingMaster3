"""The backend interface and the value types every backend speaks."""

from __future__ import annotations

import ipaddress
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable
from urllib.parse import urlparse

from meetingmaster3.errors import MM3Error

E_LLM_AUTH = "E_LLM_AUTH"
E_LLM_UNREACHABLE = "E_LLM_UNREACHABLE"
E_LLM_RATE_LIMIT = "E_LLM_RATE_LIMIT"
E_LLM_CONTEXT = "E_LLM_CONTEXT"
E_LLM_TIMEOUT = "E_LLM_TIMEOUT"
E_LLM_BAD_RESPONSE = "E_LLM_BAD_RESPONSE"
E_LLM_UNKNOWN_BACKEND = "E_LLM_UNKNOWN_BACKEND"
E_LLM_CONFIG = "E_LLM_CONFIG"
E_CONSENT_REQUIRED = "E_CONSENT_REQUIRED"

LOCAL_HOSTNAMES = frozenset({"localhost", "host.docker.internal"})


def is_local_url(url: str) -> bool:
    """True when ``url`` points at this machine (loopback or the Docker host alias)."""
    host = (urlparse(url).hostname or "").lower()
    if host in LOCAL_HOSTNAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def llm_error(code: str, message: str, hint: str = "", status_code: int = 502) -> MM3Error:
    return MM3Error(code, message, hint, status_code=status_code)


@dataclass(frozen=True)
class Message:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True)
class GenerateRequest:
    """One generation call. Give ``messages`` or ``prompt`` (a single user message)."""

    model: str
    system: str | None = None
    messages: tuple[Message, ...] = ()
    prompt: str | None = None
    temperature: float = 0.2
    max_tokens: int | None = None
    stop: tuple[str, ...] = ()
    json_mode: bool = False
    timeout: float = 300.0
    num_ctx: int | None = None  # context to allocate where the backend lets us choose (Ollama)
    think: bool | None = None
    """Reasoning ("thinking") on or off for models that support it (Ollama); ``None`` leaves
    the model's default. Other backends ignore it."""

    def chat(self) -> list[Message]:
        """The user/assistant turns, with ``prompt`` appended as a user message."""
        turns = [m for m in self.messages if m.role != "system"]
        if self.prompt is not None:
            turns.append(Message("user", self.prompt))
        if not turns:
            raise llm_error(E_LLM_CONFIG, "The request has no prompt or messages.", status_code=400)
        return turns

    def system_text(self) -> str | None:
        parts = [self.system] if self.system else []
        parts += [m.content for m in self.messages if m.role == "system"]
        return "\n\n".join(parts) or None

    def full_text(self) -> str:
        """All input text, for token estimation."""
        return "\n".join([self.system_text() or "", *(m.content for m in self.chat())])


@dataclass(frozen=True)
class Usage:
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True)
class GenerateResult:
    text: str
    model: str
    usage: Usage | None = None
    finish_reason: str | None = None
    latency_ms: int = 0


@dataclass(frozen=True)
class ModelInfo:
    id: str
    name: str | None = None
    context_window: int | None = None
    size_bytes: int | None = None


@dataclass(frozen=True)
class ConnectionStatus:
    ok: bool
    message: str
    latency_ms: int | None = None
    code: str | None = None
    hint: str = ""
    models: int | None = None
    default_model_present: bool | None = None
    details: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "message": self.message,
            "latency_ms": self.latency_ms,
            "code": self.code,
            "hint": self.hint,
            "models": self.models,
            "default_model_present": self.default_model_present,
            "details": self.details,
        }


@runtime_checkable
class LLMBackend(Protocol):
    """What a backend must provide. ``kind`` selects the registry factory."""

    id: str
    kind: str
    is_local: bool

    async def generate(self, req: GenerateRequest) -> GenerateResult: ...

    def stream(self, req: GenerateRequest) -> AsyncIterator[str]: ...

    async def list_models(self) -> list[ModelInfo]: ...

    async def test_connection(self) -> ConnectionStatus: ...

    def context_window(self, model: str) -> int | None: ...

    async def warm(self, model: str) -> None:
        """Best-effort lookup of ``model``'s context window so ``context_window`` can answer."""
        ...


def connection_failure(exc: MM3Error, latency_ms: int | None = None) -> ConnectionStatus:
    return ConnectionStatus(
        ok=False, message=exc.message, latency_ms=latency_ms, code=exc.code, hint=exc.hint
    )
