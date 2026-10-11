"""VRAM handoff with a local Ollama (spec R5).

On an 8 GB card, an Ollama model still resident from an earlier note leaves too little room for
WhisperX. Before transcription starts on the GPU, the app asks the job's LLM backend to unload its
models, but only when that backend is an Ollama on this machine. A remote or cloud backend
does not share the GPU, and an unreachable Ollama is not an error.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from meetingmaster3.config.settings import Settings

log = logging.getLogger(__name__)


def release_local_llm(settings: Settings, backend_name: str | None = None) -> list[str]:
    """Unload every model of the local Ollama backend ``backend_name`` (default backend if
    ``None``). Returns the unloaded model names; never raises."""
    if not settings.transcription.unload_ollama:
        return []
    from meetingmaster3.llm.ollama import OllamaBackend
    from meetingmaster3.llm.registry import BackendRegistry

    try:
        registry = BackendRegistry(settings)
        if registry.config(backend_name).kind != "ollama":
            return []
        backend = registry.get(backend_name)
        if not isinstance(backend, OllamaBackend) or not backend.is_local:
            return []
        unloaded = asyncio.run(backend.unload_all())
    except Exception as exc:
        log.warning("Could not ask Ollama to unload its models before transcription: %s", exc)
        return []
    if unloaded:
        log.info("Unloaded Ollama models before transcription: %s", ", ".join(unloaded))
    return unloaded
