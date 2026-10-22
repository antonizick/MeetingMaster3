from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from meetingmaster3.app import create_app
from meetingmaster3.config.settings import Settings
from meetingmaster3.logging import clear_secrets


@pytest.fixture(autouse=True)
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for var in ("MM3_CONFIG_DIR", "MM3_DATA_DIR", "MM3_CACHE_DIR", "MM3_MODELS_DIR"):
        monkeypatch.delenv(var, raising=False)
    # transcription.models.configure_model_cache() sets these; monkeypatch restores them.
    model_env = ("HF_HOME", "TORCH_HOME", "HF_HUB_OFFLINE", "HF_TOKEN", "MM3_SECRETS__HF_TOKEN")
    telemetry_env = ("PYANNOTE_METRICS_ENABLED", "HF_HUB_DISABLE_TELEMETRY", "DO_NOT_TRACK")
    for var in model_env + telemetry_env:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    # The meeting index (Phase 15i) would embed every test vault with a real local Ollama if
    # one is running. Search tests switch it on (``settings.search.enabled = True``).
    monkeypatch.setenv("MM3_SEARCH__ENABLED", "false")
    yield
    clear_secrets()


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(Settings()), base_url="http://localhost")
