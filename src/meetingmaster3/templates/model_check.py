"""Can a model write notes? Checked when a meeting is submitted, so an unusable model is caught
before transcription spends minutes on the audio, and used to suggest a model in the UI."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Sequence

from meetingmaster3.config.settings import Settings
from meetingmaster3.errors import MM3Error
from meetingmaster3.llm.base import LLMBackend, ModelInfo
from meetingmaster3.llm.registry import BackendRegistry
from meetingmaster3.templates.generator import (
    can_generate,
    context_error,
    unsuitable_model_error,
    window_is_workable,
)

TESTED_MODELS = ("qwen3:8b",)
"""Local models measured against the quality baseline (docs/PERFORMANCE.md), suggested first."""
PROBE_TIMEOUT_S = 3.0
"""How long a submission waits to learn about the model; a down server is reported later."""


def effective_window(backend: LLMBackend, window: int, max_context: int | None) -> int:
    return min(window, max_context) if max_context and backend.is_local else window


async def model_problem(
    backend: LLMBackend, model: str, max_context: int | None
) -> MM3Error | None:
    """Why ``model`` cannot write notes, when the backend can tell; None if it looks usable
    or nothing is known. Only local backends are asked, so nothing leaves the machine."""
    if not backend.is_local:
        return None
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(backend.warm(model), PROBE_TIMEOUT_S)
    if can_generate(backend, model) is False:
        return unsuitable_model_error(model)
    window = backend.context_window(model)
    if window is not None:
        room = effective_window(backend, window, max_context)
        if not window_is_workable(room):
            return context_error(model, room, window)
    return None


async def preflight(
    registry: BackendRegistry, settings: Settings, backend: str | None, model: str | None
) -> None:
    """Raise before a job is queued when its LLM model is known to be unusable."""
    name = backend or registry.default_name
    model = model or registry.config(name).default_model
    if not model:
        return  # the generate stage explains that no model is chosen
    problem = await model_problem(registry.get(name), model, settings.generation.max_context)
    if problem is not None:
        raise problem


def usable(model: ModelInfo, backend: LLMBackend, max_context: int | None) -> bool:
    if model.can_generate is False:
        return False
    if model.context_window is None:
        return True
    return window_is_workable(effective_window(backend, model.context_window, max_context))


def suggest(
    models: Sequence[ModelInfo], backend: LLMBackend, max_context: int | None
) -> str | None:
    """The model to pre-select: a tested one if installed, else the first usable one."""
    ok = [m.id for m in models if usable(m, backend, max_context)]
    for tested in TESTED_MODELS:
        for mid in ok:
            if mid in (tested, f"{tested}:latest"):
                return mid
    return ok[0] if ok else None
