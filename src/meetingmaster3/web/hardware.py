"""Hardware API: detected hardware, chosen profile, recommendations and warnings."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from meetingmaster3.hardware.detect import get_hardware
from meetingmaster3.hardware.recommend import recommend

router = APIRouter(prefix="/api/hardware")


def hardware_payload(request: Request, refresh: bool = False) -> dict[str, Any]:
    settings = request.app.state.settings
    info = get_hardware(refresh=refresh)
    rec = recommend(info, settings.hardware.profile)
    return {"hardware": info.to_dict(), "recommendation": rec.to_dict()}


@router.get("")
async def get_hardware_info(request: Request) -> dict[str, Any]:
    return hardware_payload(request)


@router.post("/refresh")
async def refresh_hardware(request: Request) -> dict[str, Any]:
    return hardware_payload(request, refresh=True)
