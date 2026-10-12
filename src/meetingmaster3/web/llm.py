"""LLM backend API: masked config, connection tests, model lists and recommendations."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from meetingmaster3.llm import recommendations
from meetingmaster3.llm.registry import BackendRegistry
from meetingmaster3.templates import model_check

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


@router.get("/backends/{name}/models")
async def backend_models(name: str, request: Request) -> dict[str, Any]:
    """Installed models; ``usable`` is false for ones that cannot write notes (embedding models,
    or a context window too small), and ``suggested`` is the one to pre-select."""
    backend = registry_for(request).get(name)
    models = await backend.list_models()
    cap = request.app.state.settings.generation.max_context
    return {
        "backend": name,
        "suggested": model_check.suggest(models, backend, cap),
        "models": [
            {
                "id": m.id,
                "name": m.name,
                "context_window": m.context_window,
                "size_bytes": m.size_bytes,
                "can_generate": m.can_generate,
                "usable": model_check.usable(m, backend, cap),
            }
            for m in models
        ],
    }


@router.get("/recommendations")
async def get_recommendations(request: Request) -> dict[str, Any]:
    return recommendations.build(request.app.state.settings.hardware.profile)
