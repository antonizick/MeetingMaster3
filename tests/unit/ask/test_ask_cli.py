"""``mm3 ask`` (Phase 15j)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from meetingmaster3.cli import app
from meetingmaster3.llm.fake import FakeLLMBackend
from meetingmaster3.llm.registry import BackendRegistry

runner = CliRunner()
CLOUD: dict[str, FakeLLMBackend] = {}


@pytest.fixture(autouse=True)
def cli_vault(ask_vault: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    config = tmp_path / "cfg" / "meetingmaster3" / "config.yaml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        yaml.safe_dump(
            {
                "vault": {"path": str(ask_vault)},
                "llm": {
                    "backends": {
                        "ollama": {"kind": "ollama", "default_model": "fake-model"},
                        "router": {
                            "kind": "openrouter",
                            "default_model": "cloud-model",
                            "consent_remembered": True,
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MM3_SEARCH__ENABLED", "true")
    local = FakeLLMBackend(id="ollama", kind="ollama")
    cloud = FakeLLMBackend(id="router", kind="openrouter", is_local=False)
    CLOUD["router"] = cloud

    def get(self: BackendRegistry, name: str | None = None) -> FakeLLMBackend:
        return cloud if name == "router" else local

    monkeypatch.setattr(BackendRegistry, "get", get)
    monkeypatch.setattr(BackendRegistry, "names", lambda self: ["ollama", "router"])
    assert runner.invoke(app, ["search", "index"]).exit_code == 0
    return ask_vault


def test_ask_prints_the_answer_and_saves_the_note(cli_vault: Path) -> None:
    r = runner.invoke(app, ["ask", "What", "about", "the", "budget", "overrun?"])
    assert r.exit_code == 0, r.output
    assert "| Date | Meeting | Attendees |" in r.stdout
    assert "Saved: MM3 Answers/" in r.stdout
    saved = r.stdout.split("Saved: ", 1)[1].strip()
    assert (cli_vault / saved).is_file()


def test_json_and_no_save(cli_vault: Path) -> None:
    r = runner.invoke(app, ["ask", "budget overrun", "--json", "--no-save", "--from", "2026-09-05"])
    assert r.exit_code == 0, r.output
    data = json.loads(r.stdout)
    assert data["saved"] is None and data["answer_id"] is None
    assert all(m["date"] >= "2026-09-05" for m in data["meetings"])
    assert {"link", "attendees", "took_part", "roles"} <= set(data["meetings"][0])
    assert not (cli_vault / "MM3 Answers").exists()


def test_a_cloud_backend_needs_allow_cloud(cli_vault: Path) -> None:
    cloud = CLOUD["router"]
    r = runner.invoke(app, ["ask", "budget?", "--backend", "router"])
    assert r.exit_code != 0 and "would send excerpts of your meetings" in r.output
    assert "--allow-cloud" in r.output
    assert cloud.calls == []  # consent_remembered (notes) does not cover Ask-AI
    r = runner.invoke(app, ["ask", "budget?", "--backend", "router", "--allow-cloud", "--no-save"])
    assert r.exit_code == 0, r.output
    assert cloud.calls


def test_an_empty_question_is_refused() -> None:
    r = runner.invoke(app, ["ask"])
    assert r.exit_code == 2
