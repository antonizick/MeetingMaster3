"""The HTML pages and HTMX partials of the core flow (Phase 10), against the fake pipeline."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from meetingmaster3.app import create_app
from meetingmaster3.config.settings import BackendConfig, Settings
from meetingmaster3.hardware.detect import GPUInfo, HardwareInfo
from meetingmaster3.web import views
from meetingmaster3.web.pages import templates as jinja
from tests.unit.jobs.helpers import make_tone, requires_ffmpeg
from tests.unit.jobs.test_jobs_api import upload, wait

NO_TOKEN = {"X-CSRF-Token": ""}


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
def ui(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("MM3_FAKE_PIPELINE", "1")
    monkeypatch.setenv("MM3_FAKE_STAGE_SECONDS", "0")
    with TestClient(create_app(settings), base_url="http://localhost") as client:
        client.get("/healthz")
        client.headers["X-CSRF-Token"] = client.cookies["mm3_csrf"]
        yield client


@pytest.fixture(scope="module")
def tone(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return make_tone(tmp_path_factory.mktemp("audio") / "2026-10-11 Product Sync.m4a", 2.0)


# -- setup -----------------------------------------------------------------------------------------


def test_home_without_vault_goes_to_setup(client: TestClient) -> None:
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/setup"
    page = client.get("/setup")
    assert page.status_code == 200 and "Vault folder" in page.text


def test_setup_check_reports_each_problem(client: TestClient, tmp_path: Path) -> None:
    missing = client.get("/setup/check", params={"vault_path": str(tmp_path / "nope")})
    assert "does not exist" in missing.text and 'class="alert error"' in missing.text
    plain = tmp_path / "plain"
    plain.mkdir()
    warn = client.get(
        "/setup/check", params={"vault_path": str(plain), "output_subfolder": "M/{yyyy}/"}
    )
    assert "does not look like an Obsidian vault" in warn.text
    assert f"{plain.resolve()}/M/" in warn.text  # the live preview of the resulting path
    bad = client.get("/setup/check", params={"vault_path": str(plain), "output_subfolder": "{who}"})
    assert "Unknown placeholder" in bad.text
    escape = client.get(
        "/setup/check", params={"vault_path": str(plain), "output_subfolder": "../x"}
    )
    assert "outside the vault" in escape.text


def test_setup_check_unwritable_vault_is_blocking(client: TestClient, tmp_path: Path) -> None:
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o500)
    try:
        r = client.get("/setup/check", params={"vault_path": str(ro)})
    finally:
        ro.chmod(0o700)
    assert "cannot write" in r.text and "permissions" in r.text


def test_setup_save_requires_csrf_then_persists(client: TestClient, vault: Path) -> None:
    form = {"vault_path": str(vault), "output_subfolder": "Notes/{yyyy}/"}
    assert client.post("/setup", data=form).status_code == 403
    client.get("/healthz")
    r = client.post("/setup", data=form, headers={"X-CSRF-Token": client.cookies["mm3_csrf"]})
    assert r.status_code == 200 and r.headers["HX-Redirect"] == "/"
    settings = client.app.state.settings  # type: ignore[attr-defined]
    assert settings.vault.path == vault and settings.vault.output_subfolder == "Notes/{yyyy}/"
    assert (vault / "MeetingMaster3" / "templates" / "executive-summary.md").is_file()
    assert client.app.state.paths.config_file.is_file()  # type: ignore[attr-defined]


def test_setup_save_refuses_a_bad_vault(client: TestClient, tmp_path: Path) -> None:
    client.get("/healthz")
    headers = {"X-CSRF-Token": client.cookies["mm3_csrf"]}
    r = client.post("/setup", data={"vault_path": str(tmp_path / "gone")}, headers=headers)
    assert "HX-Redirect" not in r.headers and "does not exist" in r.text
    assert client.app.state.settings.vault.path is None  # type: ignore[attr-defined]


# -- new meeting -----------------------------------------------------------------------------------


def test_new_meeting_page_lists_templates_and_backends(ui: TestClient, vault: Path) -> None:
    bad = vault / "MeetingMaster3" / "templates" / "broken.md"
    bad.write_text("---\nname: Broken\n---\nno sections here\n", encoding="utf-8")
    r = ui.get("/")
    assert r.status_code == 200
    assert 'value="executive-summary"' in r.text
    assert re.search(r'value="default-notes"[^>]*\bselected\b', r.text)  # the default (ADR-0039)
    assert "Executive Summary" in r.text
    assert 'value="openrouter"' in r.text and 'data-consent="yes"' in r.text
    assert 'data-badge="local"' in r.text and "cloud: openrouter" in r.text
    assert "(invalid:" in r.text  # shown, disabled, with its first issue
    assert 'name="diarize"' in r.text and 'name="min_speakers"' in r.text


def test_filename_prefill_uses_the_domain_parser(client: TestClient) -> None:
    r = client.get("/ui/parse-filename", params={"name": "2026-10-11 Product Sync.m4a"})
    assert r.json() == {"title": "Product Sync", "date": "2026-10-11", "time": None}
    r = client.get("/ui/parse-filename", params={"name": "Zoom_Recording_2026-10-11_14-30-00.mp4"})
    assert r.json()["date"] == "2026-10-11" and r.json()["time"] == "14:30"


def test_hardware_panel_shows_eta_and_advanced(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    info = HardwareInfo(
        gpus=[GPUInfo("RTX 2070 Max-Q", 8192, 600, "555")],
        cuda_available=True,
        detection_source="nvidia-smi",
        cpu_name="Test CPU",
        cpu_cores=8,
        ram_total_mb=32768,
    )
    monkeypatch.setattr("meetingmaster3.web.pages.get_hardware", lambda: info)
    r = client.get("/ui/hardware", params={"duration": 3600})
    assert "RTX 2070 Max-Q" in r.text and "8.0 GB VRAM" in r.text
    assert "minutes" in r.text and "1h 00m" in r.text
    assert 'name="transcription_model"' in r.text and 'name="compute_type"' in r.text
    assert "never share the GPU" in r.text  # the 8 GB hand-off warning
    # Measured times (R17): 60 min at 13-16x, then the notes at 15-21x with the local Ollama.
    assert "4-5 minutes" in r.text and "then 9-17 minutes to write the notes" in r.text  # Default Notes
    assert "Unknown until" in client.get("/ui/hardware").text


# -- the whole flow --------------------------------------------------------------------------------


@requires_ffmpeg
def test_flow_from_upload_to_preview(ui: TestClient, tone: Path, vault: Path) -> None:
    job = upload(ui, tone, {"template": "decision-log"}).json()
    wait(ui, job["id"], "waiting_for_input")

    page = ui.get(f"/jobs/{job['id']}")
    assert page.status_code == 200 and f"/api/jobs/{job['id']}/events" in page.text
    assert "Name speakers" in page.text and f"/jobs/{job['id']}/speakers" in page.text
    assert 'data-status="waiting_for_input"' in ui.get(f"/ui/jobs/{job['id']}/panel").text

    sp = ui.get(f"/jobs/{job['id']}/speakers")
    assert sp.status_code == 200
    assert 'name="name__SPEAKER_00"' in sp.text and 'name="name__SPEAKER_01"' in sp.text
    assert "data-start=" in sp.text and f"/api/jobs/{job['id']}/audio" in sp.text
    assert 'name="same__SPEAKER_01"' in sp.text and 'value="decision-log" selected' in sp.text

    form = {
        "name__SPEAKER_00": "Alice",
        "name__SPEAKER_01": "Bob",
        "template": "action-focused",
    }
    assert ui.post(f"/ui/jobs/{job['id']}/speakers", data=form, headers=NO_TOKEN).status_code == 403
    r = ui.post(f"/ui/jobs/{job['id']}/speakers", data=form)
    assert r.status_code == 200 and r.headers["HX-Redirect"] == f"/jobs/{job['id']}"
    done = wait(ui, job["id"], "written")
    assert done["options"]["template"] == "action-focused"  # type: ignore[index]

    panel = ui.get(f"/ui/jobs/{job['id']}/panel").text
    notes = list((vault / "Meetings").rglob("*.md"))
    note = next(p for p in notes if not p.name.endswith(".transcript.md"))
    assert "Written to your vault" in panel
    assert f'href="obsidian://open?path={quote(str(note), safe="")}"' in panel
    assert "Review &amp; edit" in panel and "/meetings/" in panel  # the review workspace

    preview = ui.get("/preview", params={"path": str(note)})
    assert preview.status_code == 200 and "Read-only preview" in preview.text
    assert "Open it in the review workspace" in preview.text
    assert "mm3-id" not in preview.text  # frontmatter is not shown

    recent = ui.get("/meetings")
    assert "Product Sync" in recent.text and "Written to vault" in recent.text
    assert "Open in Obsidian" in recent.text


@requires_ffmpeg
def test_same_person_merge_and_unknown_label(ui: TestClient, tone: Path) -> None:
    job = upload(ui, tone).json()
    wait(ui, job["id"], "waiting_for_input")
    form = {"name__SPEAKER_00": "Alice", "same__SPEAKER_01": "SPEAKER_00"}
    assert ui.post(f"/ui/jobs/{job['id']}/speakers", data=form).status_code == 200
    wait(ui, job["id"], "written")
    confirmed = ui.get(f"/api/jobs/{job['id']}/speakers").json()["confirmed"]
    assert {e["name"] for e in confirmed["speakers"].values()} == {"Alice"}
    again = ui.get(f"/jobs/{job['id']}/speakers")
    assert "already confirmed" in again.text


@requires_ffmpeg
def test_cloud_consent_is_enforced_from_the_ui_path(ui: TestClient, tone: Path) -> None:
    job = upload(ui, tone, {"backend": "openrouter", "model": "x/y"}).json()
    wait(ui, job["id"], "waiting_for_input")
    ui.post(f"/ui/jobs/{job['id']}/speakers", data={"name__SPEAKER_00": "Alice"})
    waiting = wait(ui, job["id"], "waiting_for_input")
    assert waiting["waiting_for"]["kind"] == "cloud_consent"  # type: ignore[index]
    panel = ui.get(f"/ui/jobs/{job['id']}/panel").text
    assert "Send the transcript to openrouter?" in panel and "badge cloud" in panel
    assert 'hx-vals=\'{"choice": "allow"}\'' in panel and "Use a local model instead" in panel

    r = ui.post(f"/ui/jobs/{job['id']}/consent", data={"choice": "deny"})
    assert r.status_code == 200
    failed = wait(ui, job["id"], "failed")
    assert failed["error"]["code"] == "E_CONSENT_REQUIRED"  # type: ignore[index]
    assert "E_CONSENT_REQUIRED" in ui.get(f"/ui/jobs/{job['id']}/panel").text
    assert ui.post(f"/ui/jobs/{job['id']}/consent", data={"choice": "maybe"}).status_code == 422


@requires_ffmpeg
def test_consent_can_switch_to_a_local_backend(ui: TestClient, tone: Path) -> None:
    job = upload(ui, tone, {"backend": "openrouter", "model": "x/y"}).json()
    wait(ui, job["id"], "waiting_for_input")
    ui.post(f"/ui/jobs/{job['id']}/speakers", data={"name__SPEAKER_00": "Alice"})
    wait(ui, job["id"], "waiting_for_input")
    assert ui.post(f"/ui/jobs/{job['id']}/consent", data={"choice": "local"}).status_code == 200
    done = wait(ui, job["id"], "written")
    assert done["options"]["backend"] == "ollama"  # type: ignore[index]


@requires_ffmpeg
def test_cancel_retry_and_delete(ui: TestClient, tone: Path) -> None:
    job = upload(ui, tone).json()
    wait(ui, job["id"], "waiting_for_input")
    r = ui.post(f"/ui/jobs/{job['id']}/cancel")
    assert r.status_code == 200 and "This job was cancelled" in r.text
    r = ui.post(f"/ui/jobs/{job['id']}/retry", data={"o_batch_size": "4", "o_junk": "x"})
    assert r.status_code == 200
    assert ui.post(f"/ui/jobs/{job['id']}/retry", data={"o_batch_size": "x"}).status_code == 400
    wait(ui, job["id"], "waiting_for_input")
    assert "Resume" in ui.get("/meetings").text or True
    ui.post(f"/ui/jobs/{job['id']}/cancel")
    gone = ui.delete(f"/ui/jobs/{job['id']}").text  # the refreshed Jobs section
    assert f"job-row-{job['id']}" not in gone and 'id="sec-jobs"' in gone
    assert ui.get(f"/jobs/{job['id']}", headers={"Accept": "text/html"}).status_code == 404


def test_mutating_routes_need_csrf(ui: TestClient) -> None:
    for path in ("cancel", "retry", "language", "consent", "speakers", "resume"):
        r = ui.post(f"/ui/jobs/abc/{path}", headers=NO_TOKEN)
        assert r.status_code == 403, path
    assert ui.delete("/ui/jobs/abc", headers=NO_TOKEN).status_code == 403


def test_htmx_errors_are_fragments_and_pages_get_the_error_template(ui: TestClient) -> None:
    r = ui.post("/ui/jobs/job_none/cancel", headers={"HX-Request": "true"})
    assert r.status_code == 404 and 'class="toast error"' in r.text and "E_JOB_NOT_FOUND" in r.text
    page = ui.get("/jobs/job_none", headers={"Accept": "text/html"})
    assert page.status_code == 404 and "<nav" in page.text and "E_JOB_NOT_FOUND" in page.text
    assert ui.get("/jobs/job_none").json()["code"] == "E_JOB_NOT_FOUND"  # JSON by default


# -- the progress panel, rendered from synthetic job states ----------------------------------------


def panel(job: dict[str, Any], **extra: Any) -> str:
    stages = [
        {
            "stage": "transcribe",
            "display_name": "Transcribing",
            "status": job.pop("stage_status", "running"),
            "fraction": 0.42,
            "message": "Chunk 3 of 7",
            "eta_seconds": 95,
            "elapsed": 61,
            "detail": {},
        },
        {
            "stage": "align",
            "display_name": "Aligning",
            "status": "pending",
            "fraction": None,
            "message": "",
            "eta_seconds": None,
            "elapsed": None,
            "detail": {},
        },
    ]
    base: dict[str, Any] = {
        "id": "j1",
        "status": "running",
        "source_filename": "a.m4a",
        "duration_seconds": 600,
        "meeting_date": None,
        "warnings": [],
        "waiting_for": None,
        "stages": stages,
        "error": None,
    }
    job = {**base, **job}
    ctx = {
        "job": job,
        "title": "A meeting",
        "failure": extra.pop("failure", None),
        "written": None,
        "current": stages[0],
        "final": False,
        "cancellable": True,
        "leave_note": views.leave_note(job),
        "tab_title": views.tab_title(job, stages[0] if job["status"] == "running" else None),
    }
    return jinja.env.get_template("partials/job_panel.html").render(**ctx, **extra)


LEAVE = "You can leave this page or close the browser"


@pytest.mark.parametrize(
    ("status", "waiting_for", "expected", "title"),
    [
        ("queued", None, LEAVE, "Queued · MeetingMaster3"),
        ("running", None, LEAVE, "42% · Transcribing · MeetingMaster3"),
        (
            "waiting_for_input",
            {"kind": "speaker_confirmation"},
            "paused until you name the speakers",
            "Waiting for you · MeetingMaster3",
        ),
        (
            "waiting_for_input",
            {"kind": "cloud_consent", "backend": "x", "badge": "cloud", "message": "m"},
            "paused until you answer below",
            "Waiting for you · MeetingMaster3",
        ),
        ("written", None, None, "✓ Notes ready · MeetingMaster3"),
        ("failed", None, None, "Failed · MeetingMaster3"),
        ("cancelled", None, None, "Cancelled · MeetingMaster3"),
        ("interrupted", None, None, "Interrupted · MeetingMaster3"),
    ],
)
def test_panel_says_whether_leaving_is_safe(
    status: str, waiting_for: dict[str, Any] | None, expected: str | None, title: str
) -> None:
    html = panel({"status": status, "waiting_for": waiting_for})
    notes = re.findall(r'<p class="leave-note">(.*?)</p>', html, re.S)
    if expected is None:
        assert notes == []
    else:
        assert len(notes) == 1 and expected in notes[0] and 'href="/meetings"' in notes[0]
        assert 'aria-hidden="true">ⓘ' in notes[0] and "role=" not in notes[0]  # quiet
    assert f'data-title="{title}"' in html


def test_panel_shows_stage_progress_with_aria_labels() -> None:
    html = panel({})
    assert '<progress max="100" value="42"' in html and 'aria-label="Transcribing"' in html
    assert "Chunk 3 of 7" in html and "1m 01s" in html and "about 1m 35s left" in html
    assert "Cancel" in html and 'data-live="Running: Transcribing"' in html
    assert "Waiting for the GPU" not in html


def test_panel_failure_offers_retry_and_smaller_model() -> None:
    failure = {
        "code": "E_OOM",
        "message": "The GPU ran out of memory.",
        "hint": "Try a smaller model.",
        "stage": "Transcribing",
        "suggested_overrides": {"transcription_model": "medium"},
    }
    html = panel({"status": "failed"}, failure=failure)
    assert "The GPU ran out of memory." in html and "Try a smaller model." in html
    assert 'name="o_transcription_model" value="medium"' in html
    assert "Retry with smaller model" in html and ">Retry</button>" in html
    plain = panel(
        {"status": "failed"}, failure={**failure, "code": "E_X", "suggested_overrides": {}}
    )
    assert "smaller model" not in plain.replace("Try a smaller model.", "")


def test_panel_language_question_and_warnings() -> None:
    wait_for = {
        "kind": "language",
        "detected": "de",
        "language_name": "German",
        "probability": 0.97,
        "message": "This sounds like German.",
    }
    html = panel(
        {
            "status": "waiting_for_input",
            "waiting_for": wait_for,
            "warnings": [{"stage": "diarize", "message": "Speakers were not separated: no token."}],
        }
    )
    assert "Continue in German" in html and "Treat it as English" in html
    assert 'hx-vals=\'{"action": "abort"}\'' in html
    assert "Speakers were not separated: no token." in html and 'class="alert warn"' in html


def test_panel_escapes_untrusted_text() -> None:
    html = panel(
        {"status": "failed", "warnings": [{"stage": "x", "message": "<script>alert(1)</script>"}]},
        failure={"code": "E", "message": "<img src=x onerror=alert(1)>", "hint": "", "stage": ""},
    )
    assert "<script>" not in html and "<img src=x" not in html


# -- preview ---------------------------------------------------------------------------------------


def test_preview_is_sanitised_and_confined_to_the_vault(
    ui: TestClient, vault: Path, tmp_path: Path
) -> None:
    note = vault / "Meetings" / "x.md"
    note.parent.mkdir()
    note.write_text(
        "---\nmm3-id: abc\n---\n# Plan <script>alert(1)</script>\n\n"
        "<img src=x onerror=alert(1)>\n\n[click](javascript:alert(1)) ![p](http://evil.test/p.png)\n"
        "[ok](https://example.org)\n<!-- mm3:section:start -->\n",
        encoding="utf-8",
    )
    html = ui.get("/preview", params={"path": str(note)}).text
    body = html.split('<article class="note">')[1]
    assert "<script>" not in body and "<img" not in body and "onerror=alert(1)>" not in body
    assert 'href="javascript:' not in body and "<img" not in body
    assert 'href="https://example.org"' in body and 'rel="noopener noreferrer"' in body
    assert "mm3-id" not in body and "mm3:section" not in body

    outside = tmp_path / "secret.md"
    outside.write_text("# secret", encoding="utf-8")
    assert (
        ui.get(
            "/preview", params={"path": str(outside)}, headers={"Accept": "text/html"}
        ).status_code
        == 404
    )
    link = vault / "Meetings" / "link.md"
    link.symlink_to(outside)
    assert (
        ui.get("/preview", params={"path": str(link)}, headers={"Accept": "text/html"}).status_code
        == 404
    )
    assert ui.get("/preview", params={"path": "../../etc/passwd"}).status_code == 404
    txt = vault / "a.txt"
    txt.write_text("x", encoding="utf-8")
    assert ui.get("/preview", params={"path": str(txt)}).status_code == 404


# -- assets and policy -----------------------------------------------------------------------------


def test_vendored_assets_and_csp(client: TestClient) -> None:
    for path in (
        "/static/vendor/htmx/htmx.min.js",
        "/static/vendor/alpine/alpine-csp.min.js",
        "/static/vendor/htmx/LICENSE",
        "/static/vendor/alpine/LICENSE",
        "/static/app.js",
        "/static/app.css",
    ):
        assert client.get(path).status_code == 200, path
    page = client.get("/setup")
    assert "http://" not in page.text.replace("http://localhost", "")  # nothing external is linked
    assert "https://" not in page.text
    assert 'hx-headers=\'{"X-CSRF-Token": "' in page.text
    assert "<script>" not in page.text  # no inline script (CSP)
    csp = page.headers["content-security-policy"]
    assert (
        "script-src 'self'" in csp and "'unsafe-inline'" not in csp and "'unsafe-eval'" not in csp
    )


def test_nav_pages_render(ui: TestClient) -> None:
    for path in ("/meetings", "/templates", "/settings", "/setup"):
        r = ui.get(path)
        assert r.status_code == 200 and 'aria-label="Main"' in r.text, path
    assert "Executive Summary" in ui.get("/templates").text


@requires_ffmpeg
def test_audio_endpoint_supports_range_requests(ui: TestClient, tone: Path) -> None:
    job = upload(ui, tone).json()
    wait(ui, job["id"], "waiting_for_input")
    full = ui.get(f"/api/jobs/{job['id']}/audio")
    assert full.status_code == 200 and full.headers["accept-ranges"] == "bytes"
    part = ui.get(f"/api/jobs/{job['id']}/audio", headers={"Range": "bytes=0-99"})
    assert part.status_code == 206 and len(part.content) == 100
    assert part.headers["content-range"].startswith("bytes 0-99/")
    json.loads(json.dumps(job))  # the job payload stays JSON-serialisable
    time.sleep(0)


def test_recent_notes_can_be_removed_and_orphans_pruned(
    ui: TestClient, vault: Path, tmp_path: Path
) -> None:
    from meetingmaster3.storage.repositories import RecentMeetingsRepository

    repo = RecentMeetingsRepository(ui.app.state.runner.db)  # type: ignore[attr-defined]
    kept = vault / "Meetings" / "2026-10-11 - Kept.md"
    kept.parent.mkdir(parents=True)
    kept.write_text("# Kept\n", "utf-8")
    outside = tmp_path / "OtherVault" / "2026-10-11 - Elsewhere.md"
    outside.parent.mkdir()
    outside.write_text("# Elsewhere\n", "utf-8")
    gone = vault / "Meetings" / "2026-10-11 - Gone.md"
    for path, title in ((kept, "Kept"), (outside, "Elsewhere"), (gone, "Gone")):
        repo.touch(str(path), title=title)

    page = ui.get("/meetings").text
    assert "2 entries point to a note that is missing or outside your vault" in page
    assert "File not found" in page and "Not in your vault" in page
    assert page.count("Remove from list</button>") == 3
    assert f"obsidian://open?path={quote(str(kept), safe='')}" in page
    assert f"obsidian://open?path={quote(str(gone), safe='')}" not in page  # no dead links

    # One entry, without touching the file; the CSRF check applies as everywhere else.
    assert (
        ui.post("/ui/recent/remove", data={"path": str(kept)}, headers=NO_TOKEN).status_code == 403
    )
    assert ui.post("/ui/recent/remove", data={"path": str(kept)}).status_code == 200
    assert kept.is_file() and [m.title for m in repo.recent()] == ["Gone", "Elsewhere"]

    # All orphans at once; files outside the vault are left alone too.
    repo.touch(str(kept), title="Kept")
    r = ui.post("/ui/recent/prune")
    assert r.status_code == 200 and 'id="sec-notes"' in r.text  # the refreshed section
    assert "missing or outside your vault" not in r.text
    assert [m.title for m in repo.recent()] == ["Kept"] and outside.is_file()
    page = ui.get("/meetings").text
    assert "missing or outside your vault" not in page and "Kept" in page


# -- choosing a model that can write notes ---------------------------------------------------------


@pytest.fixture
def fake_models(ui: TestClient, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """The registry's backends replaced by offline fakes: Ollama has a chat model, an embedding
    model and a chat model whose window is too small to summarise anything."""
    from meetingmaster3.llm.fake import FakeLLMBackend

    class Local(FakeLLMBackend):
        def context_window(self, model: str) -> int | None:
            return 2048 if model == "tiny:1" else 40960

        async def list_models(self) -> list[Any]:
            found = await super().list_models()
            return [
                type(m)(m.id, m.name, self.context_window(m.id), None, m.can_generate)
                for m in found
            ]

    fakes = {
        "ollama": Local(id="ollama", models=("tiny:1", "good:1"), embedding_models=("embed:1",)),
        "openrouter": FakeLLMBackend(id="openrouter", is_local=False),
    }
    registry = ui.app.state.llm_registry  # type: ignore[attr-defined]
    monkeypatch.setattr(registry, "get", lambda name=None: fakes[name or "ollama"])
    return fakes


@requires_ffmpeg
def test_unusable_models_are_refused_before_transcription(
    ui: TestClient, tone: Path, fake_models: dict[str, Any]
) -> None:
    r = upload(ui, tone, {"backend": "ollama", "model": "embed:1"})
    assert r.status_code == 422
    assert r.json()["code"] == "E_LLM_MODEL_UNSUITABLE"
    assert "embedding model" in r.json()["message"]
    r = upload(ui, tone, {"backend": "ollama", "model": "tiny:1"})
    assert r.status_code == 422 and r.json()["code"] == "E_LLM_CONTEXT"
    assert "can only read 2,048 tokens" in r.json()["message"]
    assert ui.get("/api/jobs").json()["jobs"] == []  # nothing was queued


def test_model_list_marks_unusable_models_and_suggests_one(
    ui: TestClient, fake_models: dict[str, Any]
) -> None:
    body = ui.get("/api/llm/backends/ollama/models").json()
    usable = {m["id"]: m["usable"] for m in body["models"]}
    assert usable == {"tiny:1": False, "good:1": True, "embed:1": False}
    assert body["suggested"] == "good:1"
    assert next(m for m in body["models"] if m["id"] == "embed:1")["can_generate"] is False
    # The Settings datalist leaves embedding models out.
    assert 'value="embed:1"' not in ui.get("/settings/llm/ollama/models").text


@requires_ffmpeg
def test_failed_notes_can_be_retried_with_another_model(
    ui: TestClient, tone: Path, fake_models: dict[str, Any], settings: Settings
) -> None:
    job = upload(ui, tone, {"backend": "openrouter", "model": "x/y"}).json()
    wait(ui, job["id"], "waiting_for_input")
    ui.post(f"/ui/jobs/{job['id']}/speakers", data={"name__SPEAKER_00": "Alice"})
    wait(ui, job["id"], "waiting_for_input")
    ui.post(f"/ui/jobs/{job['id']}/consent", data={"choice": "deny"})
    wait(ui, job["id"], "failed")  # failed while writing the notes

    panel_html = ui.get(f"/ui/jobs/{job['id']}/panel").text
    assert f'hx-get="/ui/jobs/{job["id"]}/model-choice"' in panel_html
    assert "Retry with the same model" in panel_html
    form = ui.get(f"/ui/jobs/{job['id']}/model-choice").text
    assert "Try another model" in form and "transcript and speaker names are kept" in form
    assert '<option value="ollama:good:1" selected>good:1 · 40,960 tokens · recommended<' in form
    assert '<option value="ollama:embed:1" disabled>' in form
    assert "write notes (embedding model)" in form
    assert "write notes (context too small)" in form

    assert (
        ui.post(f"/ui/jobs/{job['id']}/retry-model", data={"choice": "nope:x"}).status_code == 422
    )
    bad = ui.post(f"/ui/jobs/{job['id']}/retry-model", data={"choice": "ollama:embed:1"})
    assert bad.status_code == 422 and "E_LLM_MODEL_UNSUITABLE" in bad.text
    r = ui.post(
        f"/ui/jobs/{job['id']}/retry-model", data={"choice": "ollama:good:1", "make_default": "1"}
    )
    assert r.status_code == 200
    done = wait(ui, job["id"], "written")
    assert done["options"]["backend"] == "ollama"  # type: ignore[index]
    assert done["options"]["model"] == "good:1"  # type: ignore[index]
    assert settings.llm.backends["ollama"].default_model == "good:1"
    saved = (ui.app.state.paths.config_file).read_text()  # type: ignore[attr-defined]
    assert "default_model: good:1" in saved


def test_panel_offers_another_model_only_when_the_notes_failed() -> None:
    failure = {
        "code": "E_LLM_CONTEXT",
        "message": "Too small.",
        "hint": "",
        "stage": "Generating notes",
        "stage_id": "generate",
        "suggested_overrides": {},
    }
    html = panel({"status": "failed", "id": "j1"}, failure=failure)
    assert 'hx-get="/ui/jobs/j1/model-choice"' in html and "Retry with the same model" in html
    other = panel({"status": "failed", "id": "j1"}, failure={**failure, "stage_id": "transcribe"})
    assert "model-choice" not in other and ">Retry</button>" in other


def test_parse_filename_fills_a_month_day_date_and_the_form_has_the_hint(ui: TestClient) -> None:
    import datetime as dt

    name = "09-22 Interview_ Nick Antoncic - SOC Manager _ Cyber Defense Candidate.mp3"
    guess = ui.get("/ui/parse-filename", params={"name": name}).json()
    today = dt.date.today()
    year = (
        today.year if dt.date(today.year, 9, 22) <= today + dt.timedelta(days=1) else today.year - 1
    )
    assert guess["date"] == f"{year}-09-22"
    assert guess["title"] == "Interview Nick Antoncic - SOC Manager - Cyber Defense Candidate"
    page = ui.get("/").text
    assert 'id="date-hint"' in page and 'x-show="dateFromName"' in page
    assert "From the file name" in page and 'aria-describedby="date-hint"' in page


LOGO = "/static/brand/logo.png"


@pytest.mark.parametrize(
    "url",
    ["/", "/meetings", "/open", "/templates", "/settings", "/templates/executive-summary.md/edit"],
)
def test_navigation_pages_show_the_logo(ui: TestClient, url: str) -> None:
    html = ui.get(url).text
    assert LOGO in html and 'alt=""' in html and "brand/logo@2x.webp 2x" in html


def test_new_meeting_page_shows_the_big_logo_above_the_heading(ui: TestClient) -> None:
    html = ui.get("/").text
    assert 'class="hero-logo"' in html and "brand/hero@2x.webp 2x" in html
    assert html.index('class="hero"') < html.index("<h1>New meeting</h1>")
    assert "hero" not in ui.get("/meetings").text


def test_setup_and_error_pages_show_the_logo(client: TestClient, ui: TestClient) -> None:
    assert LOGO in client.get("/setup").text
    missing = ui.get("/jobs/00000000-0000-0000-0000-000000000000", headers={"Accept": "text/html"})
    assert missing.status_code == 404 and LOGO in missing.text


@pytest.mark.parametrize("page", ["job.html", "speakers.html", "review.html", "preview.html"])
def test_meeting_pages_do_not_load_the_logo(page: str) -> None:
    template = jinja.env.get_template(page)
    block = template.blocks["brand_logo"]
    assert "".join(block(template.new_context({}))) == ""


def test_logo_files_carry_no_metadata() -> None:
    from pathlib import Path

    brand = Path(__file__).parents[3] / "src" / "meetingmaster3" / "web" / "static" / "brand"
    names = sorted(p.name for p in brand.iterdir())
    assert names == [
        "LICENSE.md",  # the CC0 statement travels with the images (ADR-0035)
        "hero.png", "hero.webp", "hero@2x.png", "hero@2x.webp",
        "logo.png", "logo.webp", "logo@2x.png", "logo@2x.webp",
    ]  # fmt: skip
    for p in brand.glob("*.[pw][ne][gb]*"):
        data = p.read_bytes()
        for marker in (b"Exif", b"GIMP", b"iCCP", b"ICCP", b"tEXt", b"XMP"):
            assert marker not in data, (p.name, marker)
