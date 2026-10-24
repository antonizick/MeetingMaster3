"""A Grok share-link import end to end (Phase 15l) with a faked download: ``POST /api/imports``
with ``options.share_url``, the download in ``import_parse`` (progress, cancel, resume without a
second download), details filled from the conversation, the timed note, the New meeting page and
``mm3 import <link>``."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from meetingmaster3 import cli
from meetingmaster3.app import create_app
from meetingmaster3.config.paths import resolve_paths
from meetingmaster3.config.settings import Settings
from meetingmaster3.errors import MM3Error
from meetingmaster3.importing import stages as stages_mod
from meetingmaster3.importing.fetch import not_found, offline
from meetingmaster3.markdown.note_parser import parse_note
from meetingmaster3.markdown.transcript_format import parse_transcript
from meetingmaster3.vault.io import read_text
from tests.unit.importing.test_import_jobs import FIXTURES, UNLABELLED, written_note
from tests.unit.jobs.test_jobs_api import wait

SID = "c3ludGhldGlj_0f8b5c3e-1111-4222-8333-944445555666"
LINK = f"https://x.com/i/grok/share/{SID}?s=09"
BODY = (FIXTURES / "grok-share-linear.json").read_bytes()


class FakeFetch:
    """Stands in for :func:`fetch_share`: counts calls, returns the fixture or raises."""

    def __init__(self, *results: bytes | MM3Error | Callable[..., bytes]) -> None:
        self.results = list(results) or [BODY]
        self.calls: list[str] = []

    def __call__(self, share_id: str, **kw: Any) -> bytes:
        self.calls.append(share_id)
        result = self.results[min(len(self.calls), len(self.results)) - 1]
        if isinstance(result, MM3Error):
            raise result
        if callable(result):
            return result(**kw)
        return result


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    (root / ".obsidian").mkdir(parents=True)
    return root.resolve()


@pytest.fixture
def settings(vault: Path) -> Settings:
    s = Settings()
    s.vault.path = vault
    return s


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeFetch:
    f = FakeFetch()
    monkeypatch.setattr(stages_mod, "fetch_share", f)
    return f


@pytest.fixture
def ui(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("MM3_FAKE_PIPELINE", "1")
    monkeypatch.setenv("MM3_FAKE_STAGE_SECONDS", "0")
    with TestClient(create_app(settings), base_url="http://localhost") as client:
        client.get("/healthz")
        client.headers["X-CSRF-Token"] = client.cookies["mm3_csrf"]
        yield client


def share(client: TestClient, link: str = LINK, **options: Any) -> Any:
    return client.post(
        "/api/imports", files={"options": (None, json.dumps({"share_url": link, **options}))}
    )


def no_jobs(client: TestClient) -> bool:
    jobs = resolve_paths().jobs_dir
    on_disk = jobs.is_dir() and [p for p in jobs.iterdir() if p.is_dir()]
    return not on_disk and client.get("/api/jobs").json()["jobs"] == []


def test_a_share_link_becomes_a_timed_note(ui: TestClient, fake: FakeFetch, vault: Path) -> None:
    r = share(ui, participants=["Nick"])
    assert r.status_code == 201, r.text
    job = r.json()
    assert job["job_type"] == "import" and job["source_filename"] == "Grok share link"
    assert job["title"] == "Grok conversation" and job["duration_seconds"] is None
    assert job["options"]["import_share_id"] == SID and "share_url" not in job["options"]
    assert job["options"]["import_fill"] == ["title", "meeting_date", "meeting_time"]

    waiting = wait(ui, job["id"], "waiting_for_input")
    assert fake.calls == [SID]
    folder = resolve_paths().jobs_dir / job["id"]
    assert (folder / "source.json").read_bytes() == BODY
    assert waiting["meeting_date"] == "2026-09-14" and waiting["duration_seconds"] == 97.9
    preview = json.loads((folder / "import.json").read_text("utf-8"))
    assert preview["format"] == "grok-share" and preview["timed"]
    assert [t["start"] for t in preview["turns"][:3]] == [0.0, 12.0, 41.2]
    assert not any(t["low"] for t in preview["turns"])
    assert [s["default_name"] for s in preview["speakers"]] == ["Nick", "Grok"]

    page = ui.get(f"/jobs/{job['id']}/speakers").text
    assert "00:12" in page and "Grok share link" in page

    ui.post(f"/api/jobs/{job['id']}/input", json={"speakers": {}, "turns": {}}).raise_for_status()
    url, note = written_note(ui, job["id"], vault)
    assert note.name == "2026-09-14 - I want to plan a community garden for our street.md"
    parsed = parse_note(read_text(note)).note
    assert parsed.extra_properties["mm3-source-format"] == "grok-share"
    ct = parse_transcript(read_text(note.with_name(note.stem + ".transcript.md")))
    assert ct.doc.transcript.timed
    assert ct.doc.speakers.names == {"SPEAKER_00": "Nick", "SPEAKER_01": "Grok"}
    assert 'class="ts" data-t="12.0"' in ui.get(url).text


def test_title_and_date_come_from_the_conversation_unless_given(
    ui: TestClient, fake: FakeFetch
) -> None:
    job = share(ui, title="").json()
    done = wait(ui, job["id"], "waiting_for_input")
    assert done["title"] == "I want to plan a community garden for our street"
    assert done["options"]["meeting_time"]  # the conversation's start, in local time
    given = share(ui, title="Garden", meeting_date="2026-10-01").json()
    done = wait(ui, given["id"], "waiting_for_input")
    assert done["title"] == "Garden" and done["meeting_date"] == "2026-10-01"


@pytest.mark.parametrize(
    "link",
    [
        "https://chatgpt.com/share/6702c0de-aaaa-bbbb-cccc-1234567890ab",
        "https://example.com/some/page",
        f"http://x.com/i/grok/share/{SID}",
        f"https://grok.com.evil.com/share/{SID}",
    ],
)
def test_unsupported_links_are_refused_without_a_request(
    ui: TestClient, fake: FakeFetch, link: str
) -> None:
    r = share(ui, link)
    assert r.status_code == 422 and r.json()["code"] == "E_IMPORT_URL_UNSUPPORTED"
    assert "Markdown" in r.json()["hint"]
    assert fake.calls == [] and no_jobs(ui)


def test_a_file_and_a_link_together_are_refused(ui: TestClient, fake: FakeFetch) -> None:
    with UNLABELLED.open("rb") as fh:
        r = ui.post(
            "/api/imports",
            files={"file": (UNLABELLED.name, fh, "text/markdown")},
            data={"options": json.dumps({"share_url": LINK})},
        )
    assert r.status_code == 422 and "not both" in r.json()["message"]
    assert fake.calls == [] and no_jobs(ui)
    r = ui.post("/api/imports", files={"options": (None, json.dumps({"share_url": 7}))})
    assert r.json()["code"] == "E_IMPORT_URL_UNSUPPORTED"
    r = ui.post("/api/imports", files={"options": (None, "{}")})
    assert r.status_code == 400 and no_jobs(ui)


def test_csrf_is_required(ui: TestClient, fake: FakeFetch) -> None:
    r = ui.post(
        "/api/imports",
        files={"options": (None, json.dumps({"share_url": LINK}))},
        headers={"X-CSRF-Token": "wrong"},
    )
    assert r.status_code == 403 and fake.calls == []


@pytest.mark.parametrize(
    ("error", "code"),
    [(not_found(), "E_IMPORT_SHARE_NOT_FOUND"), (offline("ConnectError"), "E_IMPORT_OFFLINE")],
)
def test_a_failed_download_fails_the_job_and_resume_downloads_again(
    ui: TestClient, monkeypatch: pytest.MonkeyPatch, error: MM3Error, code: str
) -> None:
    f = FakeFetch(error, BODY)
    monkeypatch.setattr(stages_mod, "fetch_share", f)
    job = share(ui).json()
    failed = wait(ui, job["id"], "failed")
    assert failed["error"]["code"] == code and "Markdown" in failed["error"]["hint"]
    assert not (resolve_paths().jobs_dir / job["id"] / "source.json").exists()
    ui.post(f"/api/jobs/{job['id']}/resume").raise_for_status()
    wait(ui, job["id"], "waiting_for_input")
    assert len(f.calls) == 2


def test_an_unreadable_answer_is_not_kept(ui: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    f = FakeFetch(b'{"error": "changed"}', BODY)
    monkeypatch.setattr(stages_mod, "fetch_share", f)
    job = share(ui).json()
    failed = wait(ui, job["id"], "failed")
    assert failed["error"]["code"] == "E_IMPORT_SHARE_UNAVAILABLE"
    assert not (resolve_paths().jobs_dir / job["id"] / "source.json").exists()
    ui.post(f"/api/jobs/{job['id']}/resume").raise_for_status()
    wait(ui, job["id"], "waiting_for_input")


def test_resume_after_the_download_does_not_download_again(
    ui: TestClient, fake: FakeFetch, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = stages_mod.fill_details
    failures = [MM3Error("E_TEST", "interrupted after the download", "")]

    def flaky(ctx: Any, conv: Any) -> None:
        if failures:
            raise failures.pop()
        real(ctx, conv)

    monkeypatch.setattr(stages_mod, "fill_details", flaky)
    job = share(ui).json()
    assert wait(ui, job["id"], "failed")["error"]["code"] == "E_TEST"
    ui.post(f"/api/jobs/{job['id']}/resume").raise_for_status()
    wait(ui, job["id"], "waiting_for_input")
    assert fake.calls == [SID]


def test_cancel_during_the_download(ui: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    started = threading.Event()

    def slow(*, check: Callable[[], None], sleep: Callable[[float], None], **kw: Any) -> bytes:
        started.set()
        for _ in range(500):
            check()
            sleep(0.01)
        return BODY

    monkeypatch.setattr(stages_mod, "fetch_share", FakeFetch(slow))
    job = share(ui).json()
    assert started.wait(5)
    assert ui.post(f"/api/jobs/{job['id']}/cancel").json()["status"] == "cancelled"
    assert not (resolve_paths().jobs_dir / job["id"] / "source.json").exists()


def test_new_meeting_page_offers_the_link_field(ui: TestClient) -> None:
    page = ui.get("/?mode=import").text
    assert 'name="share_url"' in page and "downloads that one conversation from grok.com" in page


def test_mm3_import_a_link(vault: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeFetch) -> None:
    monkeypatch.setenv("MM3_FAKE_PIPELINE", "1")
    monkeypatch.setenv("MM3_FAKE_STAGE_SECONDS", "0")
    out = CliRunner().invoke(
        cli.app, ["import", LINK, "--vault", str(vault), "--yes", "--speaker", "user=Nick"]
    )
    assert out.exit_code == 0, out.output
    assert fake.calls == [SID]
    note = (
        vault
        / "Meetings"
        / "2026"
        / ("2026-09-14 - I want to plan a community garden for our street.md")
    )
    assert parse_note(read_text(note)).note.meta.speakers.names == {
        "SPEAKER_00": "Nick",
        "SPEAKER_01": "Grok",
    }


def test_mm3_import_refuses_other_links(
    vault: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeFetch
) -> None:
    monkeypatch.setenv("MM3_FAKE_PIPELINE", "1")
    out = CliRunner().invoke(
        cli.app, ["import", "https://chatgpt.com/share/abcdefgh-1234", "--vault", str(vault)]
    )
    assert out.exit_code == 1 and "Grok share link" in out.output and fake.calls == []
