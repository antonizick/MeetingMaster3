"""``/api/jobs/{id}/speakers`` and ``/api/voiceprints`` over the fake pipeline."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from meetingmaster3.app import create_app
from meetingmaster3.cli import app as cli
from meetingmaster3.config.paths import resolve_paths
from meetingmaster3.config.settings import Settings
from meetingmaster3.speakers.store import VoiceprintStore
from meetingmaster3.storage.db import Database

from ..jobs.helpers import make_tone, requires_ffmpeg
from ..jobs.test_jobs_api import upload, wait

pytestmark = requires_ffmpeg


@pytest.fixture
def settings() -> Settings:
    return Settings(privacy={"voiceprints_enabled": True})  # type: ignore[arg-type]


@pytest.fixture
def api(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("MM3_FAKE_PIPELINE", "1")
    monkeypatch.setenv("MM3_FAKE_STAGE_SECONDS", "0")
    with TestClient(create_app(settings), base_url="http://localhost") as client:
        client.get("/")
        client.headers["X-CSRF-Token"] = client.cookies["mm3_csrf"]
        yield client


@pytest.fixture(scope="module")
def tone(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return make_tone(tmp_path_factory.mktemp("audio") / "2026-10-11 Product Sync.m4a", 2.0)


def waiting_job(api: TestClient, tone: Path) -> str:
    r = upload(api, tone)
    assert r.status_code == 201, r.text
    job_id: str = r.json()["id"]
    wait(api, job_id, "waiting_for_input")
    return job_id


def test_get_speakers_before_and_while_waiting(api: TestClient, tone: Path) -> None:
    r = upload(api, tone)
    job_id = r.json()["id"]
    early = api.get(f"/api/jobs/{job_id}/speakers")
    if early.status_code != 200:  # the fake pipeline may already be waiting
        assert early.status_code == 409 and early.json()["code"] == "E_SPEAKERS_NOT_READY"
    wait(api, job_id, "waiting_for_input")
    data = api.get(f"/api/jobs/{job_id}/speakers").json()
    assert data["waiting"] is True and data["confirmed"] is None
    assert data["voiceprints_enabled"] is True and data["model_id"] == "fake/embedding"
    speaker = data["speakers"][0]
    assert {"label", "placeholder", "talk_seconds", "snippets", "candidates", "suggestion",
            "low_confidence"} <= set(speaker)  # fmt: skip
    assert speaker["snippets"] and {"start", "end"} == set(speaker["snippets"][0])
    assert '"embedding"' not in json.dumps(data)  # vectors never reach the API
    assert api.get("/api/jobs/not-a-job/speakers").status_code in (400, 404)


def test_confirm_enroll_and_second_meeting_suggests(api: TestClient, tone: Path) -> None:
    first = waiting_job(api, tone)
    r = api.post(
        f"/api/jobs/{first}/speakers",
        json={
            "SPEAKER_00": {"name": "Alice", "enroll": True},
            "SPEAKER_01": {"name": "Bob", "enroll": True},
        },
    )
    assert r.status_code == 200, r.text
    wait(api, first, "written")
    confirmed = api.get(f"/api/jobs/{first}/speakers").json()["confirmed"]
    assert confirmed["participants"] == ["Alice", "Bob"]

    people = api.get("/api/voiceprints").json()
    assert people["enabled"] is True
    assert [p["name"] for p in people["people"]] == ["Alice", "Bob"]
    assert '"embedding"' not in json.dumps(people)

    second = waiting_job(api, tone)
    data = api.get(f"/api/jobs/{second}/speakers").json()
    suggestions = {s["label"]: s["suggestion"]["name"] for s in data["speakers"]}
    assert suggestions == {"SPEAKER_00": "Alice", "SPEAKER_01": "Bob"}
    # The {"speakers": {...}} form is accepted too; one person for two labels merges them.
    alice = data["speakers"][0]["suggestion"]["person_id"]
    r = api.post(
        f"/api/jobs/{second}/speakers",
        json={"speakers": {"SPEAKER_00": {"name": "Alice", "person_id": alice},
                           "SPEAKER_01": {"name": "Alice", "person_id": alice}}},
    )  # fmt: skip
    assert r.status_code == 200, r.text
    wait(api, second, "written")
    done = api.get(f"/api/jobs/{second}/speakers").json()["confirmed"]
    assert done["participants"] == ["Alice"]


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"SPEAKER_07": "Ghost"}, "E_INPUT_INVALID"),
        ({"SPEAKER_00": {"name": ""}}, "E_INPUT_INVALID"),
        ({"SPEAKER_00": {"name": "A", "person_id": "0" * 32}}, "E_PERSON_NOT_FOUND"),
    ],
)
def test_confirm_validation(api: TestClient, tone: Path, body: dict[str, Any], code: str) -> None:
    job_id = waiting_job(api, tone)
    r = api.post(f"/api/jobs/{job_id}/speakers", json=body)
    assert r.status_code == 422 and r.json()["code"] == code
    assert api.get(f"/api/jobs/{job_id}").json()["status"] == "waiting_for_input"


def test_confirm_needs_csrf_and_a_waiting_job(api: TestClient, tone: Path) -> None:
    job_id = waiting_job(api, tone)
    token = api.headers.pop("X-CSRF-Token")
    assert api.post(f"/api/jobs/{job_id}/speakers", json={}).status_code == 403
    assert api.delete("/api/voiceprints").status_code == 403
    api.headers["X-CSRF-Token"] = token
    assert api.post(f"/api/jobs/{job_id}/speakers", json={"SPEAKER_00": "A"}).status_code == 200
    wait(api, job_id, "written")
    again = api.post(f"/api/jobs/{job_id}/speakers", json={"SPEAKER_00": "A"})
    assert again.status_code == 409 and again.json()["code"] == "E_JOB_STATE"


def test_delete_and_two_step_wipe(api: TestClient, tone: Path) -> None:
    job_id = waiting_job(api, tone)
    api.post(
        f"/api/jobs/{job_id}/speakers",
        json={"SPEAKER_00": {"name": "Alice", "enroll": True},
              "SPEAKER_01": {"name": "Bob", "enroll": True}},
    )  # fmt: skip
    wait(api, job_id, "written")
    people = api.get("/api/voiceprints").json()["people"]
    r = api.delete(f"/api/voiceprints/{people[0]['person_id']}")
    assert r.status_code == 200 and r.json()["deleted"]["name"] == "Alice"
    assert api.delete(f"/api/voiceprints/{people[0]['person_id']}").status_code == 404
    assert api.delete("/api/voiceprints/../../x").status_code == 404

    first = api.delete("/api/voiceprints")
    assert first.status_code == 428 and first.json()["code"] == "E_CONFIRM_REQUIRED"
    details = first.json()["details"]
    assert details["people"] == 1
    assert api.delete("/api/voiceprints?confirm=wrong").status_code == 428
    assert len(api.get("/api/voiceprints").json()["people"]) == 1  # nothing deleted yet
    # A cancelled job that never reached confirmation still holds its voice embeddings (S7).
    runner = api.app.state.runner  # type: ignore[attr-defined]
    stale = runner.jobs_root / job_id / "speaker_embeddings.json"
    stale.write_text("{}")
    token = api.delete("/api/voiceprints").json()["details"]["confirm_token"]
    done = api.delete(f"/api/voiceprints?confirm={token}")
    assert done.status_code == 200
    assert done.json()["deleted"] == {
        "voiceprints": 1,
        "voiceprint_embeddings": 1,
        "job_embeddings": 1,
    }
    assert not stale.exists()
    assert api.get("/api/voiceprints").json()["people"] == []
    assert api.delete(f"/api/voiceprints?confirm={token}").status_code == 428  # single use


def test_voiceprints_api_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    with TestClient(create_app(Settings()), base_url="http://localhost") as client:
        assert client.get("/api/voiceprints").json() == {"enabled": False, "people": []}


def test_cli_list_delete_wipe() -> None:
    paths = resolve_paths()
    paths.ensure()
    db = Database.open(paths.database)
    store = VoiceprintStore(db, enabled=True)
    alice = store.create_person("Alice")
    store.add_embedding(alice.person_id, [1.0, 0.0], model_id="m", seconds=90, source_job_id="j")
    store.create_person("Bob")
    db.close()
    runner = CliRunner()
    out = runner.invoke(cli, ["voiceprints", "list"])
    assert out.exit_code == 0, out.output
    assert "Voice recognition is off; 2 stored voice(s)." in out.output
    assert alice.person_id in out.output and "1.5 min" in out.output
    out = runner.invoke(cli, ["voiceprints", "delete", alice.person_id])
    assert out.exit_code == 0 and "Deleted the stored voice of Alice." in out.output
    out = runner.invoke(cli, ["voiceprints", "delete", alice.person_id])
    assert out.exit_code == 1
    out = runner.invoke(cli, ["voiceprints", "wipe"], input="n\n")
    assert out.exit_code == 1 and "Nothing deleted." in out.output
    out = runner.invoke(cli, ["voiceprints", "wipe"], input="y\n")
    assert out.exit_code == 0 and "Deleted 1 stored voice(s) and 0 sample(s)." in out.output
    out = runner.invoke(cli, ["voiceprints", "wipe", "--yes"])
    assert out.exit_code == 0 and "Deleted 0 stored voice(s)" in out.output
