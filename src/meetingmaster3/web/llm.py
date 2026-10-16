"""LLM backend API: masked config, connection tests, model lists and recommendations."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from meetingmaster3.llm import recommendations
from meetingmaster3.llm.registry import BackendRegistry
from meetingmaster3.templates.picker import build_picker, meeting_shape

router = APIRouter(prefix="/api/llm", tags=["llm"])


def registry_for(request: Request) -> BackendRegistry:
    reg: BackendRegistry = request.app.state.llm_registry
    return reg


@router.get("/backends")
async def list_backends(request: Request) -> dict[str, Any]:
    reg = registry_for(request)
    return {"default": reg.default_name, "backends": [reg.describe(n) for n in reg.names()]}


@router.post("/backends/{name}/test")
async def test_backend(name: str, request: Request) -> dict[str, object]:
    status = await registry_for(request).get(name).test_connection()
    return status.to_dict()


async def picker_for(
    request: Request, name: str, minutes: float | None = None, template: str | None = None
) -> dict[str, Any]:
    """The grouped, filtered, priced model list of backend ``name`` (shared with Settings, so the
    two pages always show the same capable set)."""
    backend = registry_for(request).get(name)
    models = await backend.list_models()
    cap = request.app.state.settings.generation.max_context
    return build_picker(backend, models, cap, meeting_shape(minutes, template))


@router.get("/backends/{name}/models")
async def backend_models(
    name: str, request: Request, minutes: float | None = None, template: str | None = None
) -> dict[str, Any]:
    """Models of a backend. ``usable`` is false (with a ``reason``) for ones that cannot write
    notes; ``recommended``/``other``/``hidden`` group them for a drop-down; ``suggested`` is the
    one to pre-select. Cloud models carry their price and an estimated cost for ``minutes`` of
    audio (default 60) with ``template``."""
    picker = await picker_for(request, name, minutes, template)
    models = [*picker["recommended"], *picker["other"], *picker["hidden"]]
    return {"backend": name, **picker, "models": sorted(models, key=lambda m: m["id"])}


@router.get("/recommendations")
async def get_recommendations(request: Request) -> dict[str, Any]:
    return recommendations.build(request.app.state.settings.hardware.profile)
