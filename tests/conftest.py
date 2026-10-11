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
    for var in ("HF_HOME", "TORCH_HOME", "HF_HUB_OFFLINE", "HF_TOKEN", "MM3_SECRETS__HF_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    yield
    clear_secrets()


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(Settings()), base_url="http://localhost")
