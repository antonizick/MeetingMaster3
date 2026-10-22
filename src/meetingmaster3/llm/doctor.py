"""Reachability and model-presence checks for every configured backend (``mm3 doctor``)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Literal

from meetingmaster3.config.settings import Settings
from meetingmaster3.errors import MM3Error
from meetingmaster3.llm.base import supports_embeddings
from meetingmaster3.llm.registry import BackendRegistry

Status = Literal["ok", "warn", "fail"]


@dataclass(frozen=True)
class BackendCheck:
    name: str
    status: Status
    detail: str
    hint: str = ""


async def _embedding_note(backend: Any, model: str) -> tuple[str, str]:
    """``(detail, hint)`` about search embeddings for the configured embedder backend."""
    try:
        models = await backend.list_embedding_models()
    except MM3Error as exc:
        return f" Embeddings: supported, models not listed ({exc.message}).", ""
    except Exception as exc:  # a diagnostic never fails the whole check
        return f" Embeddings: supported, models not listed ({type(exc).__name__}).", ""
    ids = {m.id for m in models} | {m.id.removesuffix(":latest") for m in models}
    if model in ids:
        return f" Embeddings for search: {model} is available.", ""
    hint = f"Run `ollama pull {model}`." if backend.kind == "ollama" else ""
    return f" Embeddings for search: {model} was not found.", hint


async def check_backends_async(settings: Settings) -> list[BackendCheck]:
    from meetingmaster3.search.embedder import default_backend_name

    registry = BackendRegistry(settings)
    checks: list[BackendCheck] = []
    try:
        embedder = default_backend_name(settings, registry.names(), registry.get)
    except MM3Error:
        embedder = None
    for name in registry.names():
        try:
            backend = registry.get(name)
        except MM3Error as exc:
            checks.append(BackendCheck(f"LLM {name}", "fail", exc.message, exc.hint))
            continue
        result = await backend.test_connection()
        label = f"LLM {name} ({'local' if backend.is_local else 'cloud'})"
        message, hint = result.message, result.hint
        embed_missing = False
        if result.ok and name == embedder and supports_embeddings(backend):
            note, embed_hint = await _embedding_note(backend, settings.search.embedding_model)
            message += note
            hint = " ".join(h for h in (hint, embed_hint) if h)
            embed_missing = bool(embed_hint)
        elif result.ok:
            message += " Embeddings: " + ("supported." if supports_embeddings(backend) else "no.")
        if not result.ok:
            # Not blocking: Ollama may simply not be started yet, or the user may work offline.
            checks.append(BackendCheck(label, "warn", message, hint))
        elif result.default_model_present is False or embed_missing:
            checks.append(BackendCheck(label, "warn", message, hint))
        else:
            checks.append(BackendCheck(label, "ok", message, hint))
    return checks


def check_backends(settings: Settings) -> list[BackendCheck]:
    return asyncio.run(check_backends_async(settings))
