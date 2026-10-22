"""``mm3 search`` (Phase 15i)."""

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


@pytest.fixture(autouse=True)
def cli_vault(corpus_vault: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    config = tmp_path / "cfg" / "meetingmaster3" / "config.yaml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(yaml.safe_dump({"vault": {"path": str(corpus_vault)}}), encoding="utf-8")
    monkeypatch.setenv("MM3_SEARCH__ENABLED", "true")
    fake = FakeLLMBackend(id="ollama", kind="ollama")
    monkeypatch.setattr(BackendRegistry, "get", lambda self, name=None: fake)
    return corpus_vault


def test_index_status_and_search() -> None:
    r = runner.invoke(app, ["search", "index"])
    assert r.exit_code == 0, r.output
    assert "14 added" in r.stdout
    r = runner.invoke(app, ["search", "status"])
    assert r.exit_code == 0 and "Meetings:  7 (7 notes, 7 transcripts)" in r.stdout
    r = runner.invoke(app, ["search", "certificate", "expiry"])
    assert r.exit_code == 0
    assert "Incident Retro" in r.stdout and "meaning + words" in r.stdout
    assert "**certificate**" in r.stdout


def test_json_output_and_filters() -> None:
    runner.invoke(app, ["search", "index"])
    r = runner.invoke(
        app, ["search", "budget spending costs", "--json", "--from", "2026-09-10", "--limit", "2"]
    )
    assert r.exit_code == 0
    data = json.loads(r.stdout)
    assert data["mode"] == "hybrid" and len(data["meetings"]) <= 2
    assert all(m["date"] >= "2026-09-10" for m in data["meetings"])
    assert {"mm3_id", "title", "hits", "note_path"} <= set(data["meetings"][0])


def test_rebuild_and_the_query_option() -> None:
    runner.invoke(app, ["search", "index"])
    r = runner.invoke(app, ["search", "index", "--rebuild"])
    assert r.exit_code == 0 and "14 added" in r.stdout
    r = runner.invoke(app, ["search", "--query", "index"])  # the word itself, not the command
    assert r.exit_code == 0 and "meeting(s)" in r.stdout


def test_bad_input() -> None:
    assert runner.invoke(app, ["search"]).exit_code == 2
    r = runner.invoke(app, ["search", "x", "--from", "soon"])
    assert r.exit_code == 1 and "--from and --to" in r.output


def test_search_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MM3_SEARCH__ENABLED", "false")
    r = runner.invoke(app, ["search", "budget"])
    assert r.exit_code == 1 and "switched off" in r.output
