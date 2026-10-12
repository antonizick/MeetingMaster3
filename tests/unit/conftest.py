from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from meetingmaster3.app import create_app
from meetingmaster3.config.settings import Settings


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    (root / ".obsidian").mkdir(parents=True)
    return root.resolve()


@pytest.fixture
def app_settings(vault: Path) -> Settings:
    s = Settings()
    s.vault.path = vault
    return s


@pytest.fixture
def ui(app_settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A client with the started app (database, runner) and a valid CSRF header."""
    monkeypatch.setenv("MM3_FAKE_PIPELINE", "1")
    monkeypatch.setenv("MM3_FAKE_STAGE_SECONDS", "0")
    with TestClient(create_app(app_settings), base_url="http://localhost") as client:
        client.get("/healthz")
        client.headers["X-CSRF-Token"] = client.cookies["mm3_csrf"]
        yield client


def config_file(client: TestClient) -> Path:
    path: Path = client.app.state.paths.config_file  # type: ignore[attr-defined]
    return path
