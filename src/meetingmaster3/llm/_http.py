"""Shared httpx plumbing: bounded retries with jitter and error normalisation."""

from __future__ import annotations

import asyncio
import json
import logging
import random
from collections.abc import Awaitable, Callable

import httpx

from meetingmaster3.errors import MM3Error
from meetingmaster3.llm.base import (
    E_LLM_AUTH,
    E_LLM_BAD_RESPONSE,
    E_LLM_CONTEXT,
    E_LLM_RATE_LIMIT,
    E_LLM_TIMEOUT,
    E_LLM_UNREACHABLE,
    llm_error,
)
from meetingmaster3.logging import redact

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 4
BASE_DELAY_S = 0.5
MAX_DELAY_S = 20.0
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
REASON_CHARS = 300
"""How much of a provider's own error message a 4xx error shows (``provider_reason``)."""
CONTEXT_MARKERS = (
    "context length",
    "context_length",
    "context window",
    "maximum context",
    "too many tokens",
    "prompt is too long",
    "input is too long",
    "exceeds the context",
)

Sleep = Callable[[float], Awaitable[None]]


def backoff_delay(attempt: int, retry_after: float | None = None) -> float:
    """Exponential backoff with full jitter; a server ``Retry-After`` raises the floor."""
    ceiling = min(MAX_DELAY_S, BASE_DELAY_S * 2**attempt)
    delay = random.uniform(ceiling / 2, ceiling)  # noqa: S311 (jitter, not security)
    return min(MAX_DELAY_S, max(delay, retry_after or 0.0))


def _retry_after(resp: httpx.Response) -> float | None:
    try:
        return float(resp.headers["retry-after"])
    except (KeyError, ValueError):
        return None


def looks_like_context_error(text: str) -> bool:
    low = text.lower()
    return any(marker in low for marker in CONTEXT_MARKERS)


def error_from_response(provider: str, resp: httpx.Response, body: str | None = None) -> MM3Error:
    """Map a non-2xx response to a normalised ``MM3Error``. The body is never logged above DEBUG."""
    text = body if body is not None else resp.text
    log.debug("%s HTTP %s: %s", provider, resp.status_code, redact(text[:500]))
    status = resp.status_code
    if status in (401, 403):
        return llm_error(
            E_LLM_AUTH,
            f"{provider} rejected the credentials (HTTP {status}).",
            "Check the API key for this backend in Settings.",
            status_code=401,
        )
    if status == 429:
        return llm_error(
            E_LLM_RATE_LIMIT,
            f"{provider} is rate limiting requests.",
            "Wait a moment and retry, or pick another model or backend.",
            status_code=429,
        )
    if status in (400, 413, 422) and looks_like_context_error(text):
        return llm_error(
            E_LLM_CONTEXT,
            f"The prompt does not fit the model's context window ({provider}).",
            "Use a model with a larger context or let the app split the transcript.",
            status_code=413,
        )
    if status == 408 or status == 504:
        return llm_error(E_LLM_TIMEOUT, f"{provider} timed out (HTTP {status}).", status_code=504)
    reason = provider_reason(text) if 400 <= status < 500 else ""
    return MM3Error(
        E_LLM_BAD_RESPONSE,
        f"{provider} returned HTTP {status}" + (f": {reason}" if reason else "."),
        "Check the backend's logs and that the selected model exists.",
        status_code=502,
        details={"provider_reason": reason} if reason else None,
    )


def provider_reason(text: str) -> str:
    """The provider's own short explanation from a JSON error body (``{"error": {"message":
    ...}}``, ``{"error": "..."}`` or ``{"message": ...}``), redacted and capped; else ``""``."""
    try:
        data = json.loads(text)
    except ValueError:
        return ""
    if not isinstance(data, dict):
        return ""
    error = data.get("error", data)
    message = error.get("message") if isinstance(error, dict) else error
    if not isinstance(message, str):
        return ""
    return redact(" ".join(message.split()))[:REASON_CHARS]


def error_from_exception(provider: str, exc: Exception) -> MM3Error:
    if isinstance(exc, MM3Error):
        return exc
    if isinstance(exc, httpx.TimeoutException):
        return llm_error(
            E_LLM_TIMEOUT,
            f"{provider} did not answer in time.",
            "Try a smaller model or a longer timeout.",
            status_code=504,
        )
    if isinstance(exc, httpx.TransportError):
        return llm_error(
            E_LLM_UNREACHABLE,
            f"Cannot reach {provider}.",
            "Check that the server is running and the base URL is correct.",
            status_code=503,
        )
    return llm_error(E_LLM_BAD_RESPONSE, f"Unexpected {provider} failure: {type(exc).__name__}.")


async def send(
    client: httpx.AsyncClient,
    request: httpx.Request,
    provider: str,
    *,
    stream: bool = False,
    attempts: int = MAX_ATTEMPTS,
    sleep: Sleep = asyncio.sleep,
) -> httpx.Response:
    """Send with bounded retries on 429/5xx and connect errors. Raises ``MM3Error``.

    With ``stream=True`` the caller owns closing the returned response. Cancellation
    (``asyncio.CancelledError``) is never swallowed, so a cancelled job stops mid-backoff.
    """
    for attempt in range(attempts):
        last = attempt == attempts - 1
        try:
            resp = await client.send(request, stream=stream)
        except httpx.HTTPError as exc:
            if last or isinstance(exc, httpx.TimeoutException):
                raise error_from_exception(provider, exc) from exc
            await sleep(backoff_delay(attempt))
            continue
        if resp.status_code < 400:
            return resp
        body = (await resp.aread()).decode("utf-8", "replace") if stream else resp.text
        retry_after = _retry_after(resp)
        if stream:
            await resp.aclose()
        if resp.status_code in RETRY_STATUSES and not last:
            await sleep(backoff_delay(attempt, retry_after))
            continue
        raise error_from_response(provider, resp, body)
    raise AssertionError("unreachable")  # pragma: no cover
