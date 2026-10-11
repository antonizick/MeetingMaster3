"""Reachability and model-presence checks for every configured backend (``mm3 doctor``)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Literal

from meetingmaster3.config.settings import Settings
from meetingmaster3.errors import MM3Error
from meetingmaster3.llm.registry import BackendRegistry

Status = Literal["ok", "warn", "fail"]


@dataclass(frozen=True)
class BackendCheck:
    name: str
    status: Status
    detail: str
    hint: str = ""


async def check_backends_async(settings: Settings) -> list[BackendCheck]:
    registry = BackendRegistry(settings)
    checks: list[BackendCheck] = []
    for name in registry.names():
        try:
            backend = registry.get(name)
        except MM3Error as exc:
            checks.append(BackendCheck(f"LLM {name}", "fail", exc.message, exc.hint))
            continue
        result = await backend.test_connection()
        label = f"LLM {name} ({'local' if backend.is_local else 'cloud'})"
        if not result.ok:
            # Not blocking: Ollama may simply not be started yet, or the user may work offline.
            checks.append(BackendCheck(label, "warn", result.message, result.hint))
        elif result.default_model_present is False:
            checks.append(BackendCheck(label, "warn", result.message, result.hint))
        else:
            checks.append(BackendCheck(label, "ok", result.message, result.hint))
    return checks


def check_backends(settings: Settings) -> list[BackendCheck]:
    return asyncio.run(check_backends_async(settings))
