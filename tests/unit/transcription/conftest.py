from __future__ import annotations

from typing import Any

import pytest

from meetingmaster3.hardware import detect
from meetingmaster3.hardware.detect import GPUInfo, HardwareInfo

VRAM8 = HardwareInfo(
    gpus=[GPUInfo("RTX 2070 Max-Q (test)", 8192, 500, "1.0")],
    cuda_available=True,
    ram_total_mb=32000,
)


@pytest.fixture(autouse=True)
def vram8_hardware(monkeypatch: pytest.MonkeyPatch) -> HardwareInfo:
    """Every transcription test sees the 8 GB reference GPU (no nvidia-smi call)."""
    monkeypatch.setattr(detect, "get_hardware", lambda refresh=False: VRAM8)
    return VRAM8


@pytest.fixture(autouse=True)
def handoff_calls(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Record the Ollama handoff instead of calling a real Ollama."""
    from meetingmaster3.transcription import handoff

    calls: list[Any] = []

    def fake(settings: Any, backend: str | None = None) -> list[str]:
        calls.append(backend)
        return []

    monkeypatch.setattr(handoff, "release_local_llm", fake)
    return calls
