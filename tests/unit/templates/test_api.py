"""Templates and generation API with the fake pipeline writing into a temporary vault."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from meetingmaster3.app import create_app
from meetingmaster3.config.settings import BackendConfig, Settings
from meetingmaster3.llm.fake import FakeLLMBackend
from tests.unit.jobs.helpers import make_tone, requires_ffmpeg
from tests.unit.jobs.test_jobs_api import upload, wait

pytestmark = requires_ffmpeg
SPEAKERS = {"SPEAKER_00": {"name": "Alice"}, "SPEAKER_01": {"name": "Bob"}}


class FakeRegistry:
    default_name = "ollama"

    def __init__(self) -> None:
        self.backends: list[FakeLLMBackend] = []

    def get(self, name: str | None = None) -> FakeLLMBackend:
        name = name or self.default_name
        backend = FakeLLMBackend(
            id=name,
            is_local=name != "openrouter",
            responder=lambda req: "Regenerated body.\n\n- with a list",
        )
        self.backends.append(backend)
        return backend


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    (root / ".obsidian").mkdir(parents=True)
    return root.resolve()


@pytest.fixture
def settings(vault: Path) -> Settings:
    s = Settings()
    s.vault.path = vault
    s.llm.backends["openrouter"] = BackendConfig(kind="openrouter", api_key="sk-test")
    return s


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


def process(api: TestClient, tone: Path, **options: Any) -> dict[str, Any]:
    job = upload(api, tone, options).json()
    wait(api, job["id"], "waiting_for_input")
    assert api.post(f"/api/jobs/{job['id']}/speakers", json=SPEAKERS).status_code == 200
    return job


def test_templates_are_installed_and_listed(api: TestClient, vault: Path) -> None:
    folder = vault / "MeetingMaster3" / "templates"
    assert sorted(p.name for p in folder.glob("*.md")) == [
        "action-focused.md",
        "decision-log.md",
        "executive-summary.md",
        "just-the-facts.md",
        "technical-deep-dive.md",
    ]
    data = api.get("/api/templates").json()
    assert data["default"] == "executive-summary"
    ids = {t["id"]: t for t in data["templates"]}
    assert set(ids) == {p.stem for p in folder.glob("*.md")}
    assert ids["decision-log"]["source"] == "vault" and ids["decision-log"]["valid"]
    assert ids["decision-log"]["sections"][-1]["id"] == "ai-recommendations"

    (folder / "broken.md").write_text("---\nid: broken\n---\n", encoding="utf-8")
    listed = api.get("/api/templates").json()["templates"]
    assert listed[-1]["file"] == "broken.md" and listed[-1]["valid"] is False


def test_install_endpoint_and_csrf(api: TestClient, vault: Path) -> None:
    edited = vault / "MeetingMaster3" / "templates" / "just-the-facts.md"
    edited.write_text(edited.read_text("utf-8") + "\nmine\n", encoding="utf-8")
    r = api.post("/api/templates/install")
    assert r.status_code == 200
    actions = {x["file"]: x["action"] for x in r.json()["results"]}
    assert actions["just-the-facts.md"] == "kept" and actions["decision-log.md"] == "unchanged"
    token = api.headers.pop("X-CSRF-Token")
    assert api.post("/api/templates/install").status_code == 403
    assert api.post("/api/notes/regenerate-section", json={}).status_code == 403
    api.headers["X-CSRF-Token"] = token


def test_full_flow_writes_note_then_regenerates_a_section(
    api: TestClient, tone: Path, vault: Path
) -> None:
    job = process(api, tone, template="decision-log", tags=["product"])
    done = wait(api, job["id"], "written")
    assert [s["status"] for s in done["stages"]][-2:] == ["completed", "completed"]
    notes = [p for p in vault.rglob("*.md") if "templates" not in p.parts]
    note = next(p for p in notes if not p.name.endswith(".transcript.md"))
    assert note.name == "2026-10-11 - Product Sync.md"
    text = note.read_text("utf-8")
    assert "mm3-template: decision-log" in text and "tags: [meeting, product]" in text

    registry = FakeRegistry()
    api.app.state.llm_registry = registry  # type: ignore[attr-defined]
    rel = note.relative_to(vault).as_posix()
    r = api.post(
        "/api/notes/regenerate-section",
        json={"note": rel, "section_id": "summary", "instructions": "Shorter."},
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["note"] == rel and out["template"] == "decision-log"
    assert out["backend"] == "ollama" and out["model"] == "fake-model"
    assert out["new_body"] == "Regenerated body.\n\n- with a list"
    assert out["old_body"].startswith("Simulated summary")
    assert out["unified_diff"].startswith("--- before\n+++ after")
    assert out["stats"]["changed"] >= 1 and out["side_by_side"][0]["kind"] == "replace"
    assert note.read_text("utf-8") == text  # preview only: nothing written
    prompt = registry.backends[-1].calls[0].messages[0].content
    assert "Shorter." in prompt and "<previous_version>" in prompt


def test_regenerate_errors(api: TestClient, tone: Path, vault: Path) -> None:
    job = process(api, tone)
    wait(api, job["id"], "written")
    api.app.state.llm_registry = FakeRegistry()  # type: ignore[attr-defined]
    note = next(p for p in vault.rglob("2026-10-11 - Product Sync.md"))
    rel = note.relative_to(vault).as_posix()

    def regen(**body: Any) -> Any:
        return api.post("/api/notes/regenerate-section", json={"note": rel, **body})

    r = regen(section_id="nope")
    assert r.status_code == 404 and r.json()["code"] == "E_SECTION_NOT_FOUND"
    r = regen(section_id="summary", backend="openrouter")
    assert r.status_code == 422 and r.json()["code"] == "E_LLM_CONFIG"  # no model for it
    r = regen(section_id="summary", backend="openrouter", model="x/y")
    assert r.status_code == 403 and r.json()["code"] == "E_CONSENT_REQUIRED"
    ok = regen(section_id="summary", backend="openrouter", model="x/y", cloud_consent=True)
    assert ok.status_code == 200 and ok.json()["model"] == "x/y"
    r = api.post(
        "/api/notes/regenerate-section", json={"note": "../outside.md", "section_id": "summary"}
    )
    assert r.json()["code"] == "vault_path_escape"
    r = api.post(
        "/api/notes/regenerate-section",
        json={"note": rel.replace(".md", ".transcript.md"), "section_id": "summary"},
    )
    assert r.status_code == 404 and r.json()["code"] == "E_NOTE_NOT_FOUND"
    assert regen(section_id="summary", extra=1).status_code == 422

    text = note.read_text("utf-8")
    note.write_text(text.replace("<!-- /mm3:section:summary -->\n", "", 1), encoding="utf-8")
    r = regen(section_id="summary")
    assert r.status_code == 409 and r.json()["code"] == "section_markers_invalid"
    note.write_text(text, encoding="utf-8")

    note.with_name(note.stem + ".transcript.md").unlink()
    r = regen(section_id="summary")
    assert r.status_code == 409 and r.json()["code"] == "E_TRANSCRIPT_MISSING"


def test_generate_endpoint_sets_template_before_generation(api: TestClient, tone: Path) -> None:
    job = upload(api, tone).json()
    wait(api, job["id"], "waiting_for_input")
    r = api.post(f"/api/jobs/{job['id']}/generate", json={"template": "action-focused"})
    assert r.status_code == 200 and r.json()["options"]["template"] == "action-focused"
    assert r.json()["status"] == "waiting_for_input"  # still waiting for the speakers
    api.post(f"/api/jobs/{job['id']}/speakers", json=SPEAKERS)
    wait(api, job["id"], "written")
    r = api.post(f"/api/jobs/{job['id']}/generate", json={"template": "decision-log"})
    assert r.status_code == 409 and r.json()["code"] == "E_JOB_STATE"
    r = api.post(f"/api/jobs/{job['id']}/generate", json={"bogus": 1})
    assert r.status_code == 422


def test_generate_endpoint_answers_cloud_consent(api: TestClient, tone: Path, vault: Path) -> None:
    job = process(api, tone, backend="openrouter")
    waiting = wait(api, job["id"], "waiting_for_input")
    assert waiting["waiting_for"]["kind"] == "cloud_consent"
    assert waiting["waiting_for"]["badge"] == "cloud: fake"
    r = api.post(f"/api/jobs/{job['id']}/generate", json={"cloud_consent": True})
    assert r.status_code == 200
    wait(api, job["id"], "written")


def test_generate_endpoint_switches_to_local_backend(api: TestClient, tone: Path) -> None:
    job = process(api, tone, backend="openrouter")
    wait(api, job["id"], "waiting_for_input")
    api.post(f"/api/jobs/{job['id']}/generate", json={"backend": "ollama"})
    done = wait(api, job["id"], "written")
    assert done["options"]["backend"] == "ollama"


def test_generate_endpoint_resumes_a_failed_job(
    api: TestClient, tone: Path, settings: Settings
) -> None:
    job = process(api, tone, backend="openrouter")
    wait(api, job["id"], "waiting_for_input")
    api.post(f"/api/jobs/{job['id']}/input", json={"consent": False})
    failed = wait(api, job["id"], "failed")
    assert failed["error"]["code"] == "E_CONSENT_REQUIRED"
    r = api.post(
        f"/api/jobs/{job['id']}/generate", json={"backend": "ollama", "template": "just-the-facts"}
    )
    assert r.status_code == 200
    wait(api, job["id"], "written")
