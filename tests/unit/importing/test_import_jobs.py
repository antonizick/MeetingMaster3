"""The ``import`` job end to end (Phase 15k): ``POST /api/imports``, the check-the-speakers page,
the fake LLM, the vault output, resume and cancel, and an imported meeting in the review
workspace (rename, template switch, regenerate) and in ``mm3 import``."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from meetingmaster3 import cli
from meetingmaster3.app import create_app
from meetingmaster3.config.paths import resolve_paths
from meetingmaster3.config.settings import Settings
from meetingmaster3.errors import MM3Error
from meetingmaster3.importing.stages import ImportParseStage
from meetingmaster3.jobs import pipeline as pipeline_mod
from meetingmaster3.jobs.fakes import FakeGenerate, FakeWrite
from meetingmaster3.jobs.pipeline import build_pipeline
from meetingmaster3.jobs.stage import StageContext
from meetingmaster3.markdown.note_parser import parse_note
from meetingmaster3.markdown.transcript_format import parse_transcript
from meetingmaster3.vault.io import read_text
from tests.unit.jobs.test_jobs_api import wait
from tests.unit.web.test_review import Workspace

FIXTURES = Path(__file__).parents[2] / "fixtures" / "imports"
UNLABELLED = FIXTURES / "voice-mode-unlabelled.md"
TIMESTAMPED = FIXTURES / "timestamped.txt"


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
def ui(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("MM3_FAKE_PIPELINE", "1")
    monkeypatch.setenv("MM3_FAKE_STAGE_SECONDS", "0")
    with TestClient(create_app(settings), base_url="http://localhost") as client:
        client.get("/healthz")
        client.headers["X-CSRF-Token"] = client.cookies["mm3_csrf"]
        yield client


def upload(client: TestClient, path: Path, options: dict[str, Any] | None = None) -> Any:
    with path.open("rb") as fh:
        return client.post(
            "/api/imports",
            files={"file": (path.name, fh, "text/markdown")},
            data={"options": json.dumps(options or {})},
        )


def check_form(client: TestClient, job_id: str) -> tuple[str, dict[str, str]]:
    """The check page and its default form fields."""
    page = client.get(f"/jobs/{job_id}/speakers")
    assert page.status_code == 200, page.text
    fields = dict(re.findall(r'name="((?:name|turn)__[^"]+)"[^>]*?value="([^"]*)"', page.text))
    fields.update(
        {m[0]: m[1] for m in re.findall(r'name="(turn__\d+)" value="([^"]*)"', page.text)}
    )
    return page.text, fields


def written_note(client: TestClient, job_id: str, vault: Path) -> tuple[str, Path]:
    wait(client, job_id, "written")
    page = client.get(f"/jobs/{job_id}").text
    link = re.search(r'href="(/meetings/[^"]+)"', page)
    assert link, page
    url = link.group(1).replace("&amp;", "&")
    return url, vault / parse_qs(urlparse(url).query)["path"][0]


def test_import_an_unlabelled_conversation_flip_a_turn_and_write(
    ui: TestClient, vault: Path
) -> None:
    r = upload(ui, UNLABELLED, {"participants": ["Nick"], "tags": ["ai-chat"]})
    assert r.status_code == 201, r.text
    job = r.json()
    assert job["job_type"] == "import" and job["title"] == "voice-mode-unlabelled"
    assert [s["stage"] for s in job["stages"]] == [
        "import_parse",
        "await_speaker_confirmation",
        "generate",
        "write",
    ]
    assert job["audio"]["retention"]["kind"] == "none" and job["duration_seconds"] is None
    folder = resolve_paths().jobs_dir / job["id"]
    assert (folder / "source.md").is_file() and not list(folder.glob("original.*"))

    waiting = wait(ui, job["id"], "waiting_for_input")
    question = waiting["waiting_for"]
    assert question["kind"] == "import_confirmation" and question["turns"] > 20  # type: ignore[index,operator]
    assert any("guessed" in w["message"] for w in waiting["warnings"])  # type: ignore[union-attr,index]
    panel = ui.get(f"/ui/jobs/{job['id']}/panel").text
    assert "Who said what?" in panel and "paused until you name the speakers" in panel

    html, fields = check_form(ui, job["id"])
    assert fields["name__SPEAKER_00"] == "Nick" and fields["name__SPEAKER_01"] == "AI"
    assert "Fair enough." in html and 'class="who spk-0"' in html
    first_answer = fields["turn__1"]
    assert first_answer == "SPEAKER_01"
    form = {
        **fields,
        "name__SPEAKER_01": "Grok",
        "turn__1": "SPEAKER_00",
        "template": "default-notes",
    }
    r = ui.post(f"/ui/jobs/{job['id']}/import-check", data=form)
    assert r.status_code == 200 and r.headers["HX-Redirect"] == f"/jobs/{job['id']}"

    url, note = written_note(ui, job["id"], vault)
    parsed = parse_note(read_text(note))
    meta = parsed.note.meta
    assert meta.participants == ["Nick", "Grok"] and "ai-chat" in meta.tags
    assert parsed.note.extra_properties == {
        "mm3-source": "import",
        "mm3-source-format": "chat-unlabelled",
    }
    companion = note.with_name(note.stem + ".transcript.md")
    ct = parse_transcript(read_text(companion))
    assert not ct.doc.transcript.timed and ct.doc.extra_properties["mm3-source"] == "import"
    assert ct.doc.transcript.segments[1].speaker_label == "SPEAKER_00"  # the flipped turn
    assert ct.doc.speakers.names == {"SPEAKER_00": "Nick", "SPEAKER_01": "Grok"}
    assert "[00:" not in read_text(companion).split("<!-- mm3:transcript-data")[0]
    readable = note.with_name(note.stem + " (Transcript).md")
    assert readable.is_file() and "Grok</mark>" in read_text(readable)
    assert "[00:" not in read_text(note)

    page = ui.get(url).text
    assert "Imported from AI conversation (unlabelled)" in page
    assert 'id="audio"' not in page and "so there is no recording" in page
    assert 'class="ts"' not in page
    meetings = ui.get("/meetings").text
    assert "voice-mode-unlabelled" in meetings


def test_check_answers_are_validated(ui: TestClient) -> None:
    job = upload(ui, UNLABELLED).json()
    wait(ui, job["id"], "waiting_for_input")
    _, fields = check_form(ui, job["id"])
    bad_label = ui.post(
        f"/ui/jobs/{job['id']}/import-check", data={**fields, "turn__2": "SPEAKER_09"}
    )
    assert bad_label.status_code == 422 and bad_label.json()["code"] == "E_INPUT_INVALID"
    bad_json = ui.post(f"/api/jobs/{job['id']}/input", json={"speakers": {"x y": "A"}})
    assert bad_json.status_code == 422
    bad_turn = ui.post(f"/api/jobs/{job['id']}/input", json={"turns": {"first": "SPEAKER_00"}})
    assert bad_turn.status_code == 422
    assert ui.get(f"/api/jobs/{job['id']}").json()["status"] == "waiting_for_input"


def test_timestamped_import_keeps_times(ui: TestClient, vault: Path) -> None:
    job = upload(ui, TIMESTAMPED, {"meeting_date": "2026-10-20"}).json()
    assert job["duration_seconds"] == 80.0
    wait(ui, job["id"], "waiting_for_input")
    r = ui.post(f"/api/jobs/{job['id']}/input", json={"speakers": {}, "turns": {}})
    assert r.status_code == 200, r.text
    url, note = written_note(ui, job["id"], vault)
    assert note.name == "2026-10-20 - timestamped.md"
    companion = read_text(note.with_name(note.stem + ".transcript.md"))
    assert "**[00:00:04] Alice:** Morning, everyone." in companion
    page = ui.get(url).text
    assert 'class="ts" data-t="11.0"' in page and "Imported from timestamped transcript" in page


def test_upload_errors_leave_no_job(ui: TestClient, tmp_path: Path) -> None:
    binary = tmp_path / "recording.md"
    binary.write_bytes(b"ID3\x00\x00binary audio")
    r = upload(ui, binary)
    assert r.status_code == 422 and r.json()["code"] == "E_IMPORT_UNREADABLE"
    big = tmp_path / "big.md"
    big.write_bytes(b"word " * (11 * 1024 * 1024 // 5))
    r = upload(ui, big)
    assert r.status_code == 413 and r.json()["code"] == "E_IMPORT_TOO_LARGE"
    jobs = resolve_paths().jobs_dir
    assert not jobs.is_dir() or not [p for p in jobs.iterdir() if p.is_dir()]
    assert ui.get("/api/jobs").json()["jobs"] == []


def test_csrf_is_required(ui: TestClient) -> None:
    with UNLABELLED.open("rb") as fh:
        r = ui.post(
            "/api/imports",
            files={"file": (UNLABELLED.name, fh, "text/markdown")},
            headers={"X-CSRF-Token": "wrong"},
        )
    assert r.status_code == 403


def test_cancel_resume_pin_and_audio(ui: TestClient, vault: Path) -> None:
    job = upload(ui, UNLABELLED).json()
    wait(ui, job["id"], "waiting_for_input")
    assert ui.post(f"/api/jobs/{job['id']}/pin").json()["code"] == "E_AUDIO_MISSING"
    assert ui.get(f"/api/jobs/{job['id']}/audio").status_code == 404
    assert ui.post(f"/api/jobs/{job['id']}/cancel").json()["status"] == "cancelled"
    ui.post(f"/api/jobs/{job['id']}/resume").raise_for_status()
    again = wait(ui, job["id"], "waiting_for_input")
    parse = next(s for s in again["stages"] if s["stage"] == "import_parse")  # type: ignore[union-attr]
    assert parse["attempt"] == 1  # the parsed file was kept
    ui.post(f"/api/jobs/{job['id']}/input", json={"speakers": {}, "turns": {}}).raise_for_status()
    written_note(ui, job["id"], vault)
    assert ui.get(f"/api/jobs/{job['id']}").json()["audio"]["retention"]["kind"] == "none"


class FailOnce:
    """Make the named stage fail on its first run only."""

    def __init__(self, stage: Any) -> None:
        self.stage, self.failed = stage, False
        self.name, self.display_name = stage.name, stage.display_name
        self.uses_gpu = False

    def __getattr__(self, item: str) -> Any:
        return getattr(self.stage, item)

    def run(self, ctx: StageContext) -> Path:
        if not self.failed:
            self.failed = True
            raise MM3Error("E_TEST", "boom", "")
        return Path(self.stage.run(ctx))


@pytest.mark.parametrize("stage", ["import_parse", "generate", "write"])
def test_resume_after_a_failure_at_each_stage(
    settings: Settings, vault: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    monkeypatch.setenv("MM3_FAKE_STAGE_SECONDS", "0")
    flaky = {
        "import_parse": FailOnce(ImportParseStage()),
        "generate": FailOnce(FakeGenerate(0)),
        "write": FailOnce(FakeWrite(0)),
    }
    key = "import:import_parse" if stage == "import_parse" else stage
    monkeypatch.setitem(pipeline_mod._REGISTRY, key, lambda s: flaky[stage])
    if stage != "generate":
        monkeypatch.setitem(pipeline_mod._REGISTRY, "generate", lambda s: FakeGenerate(0))
    if stage != "write":
        monkeypatch.setitem(pipeline_mod._REGISTRY, "write", lambda s: FakeWrite(0))
    with TestClient(create_app(settings), base_url="http://localhost") as client:
        client.get("/healthz")
        client.headers["X-CSRF-Token"] = client.cookies["mm3_csrf"]
        job = upload(client, UNLABELLED, {"import_confirmed": True}).json()
        failed = wait(client, job["id"], "failed")
        assert failed["error"]["code"] == "E_TEST"  # type: ignore[index]
        client.post(f"/api/jobs/{job['id']}/resume").raise_for_status()
        done = wait(client, job["id"], "written")
        attempts = {s["stage"]: s["attempt"] for s in done["stages"]}  # type: ignore[union-attr]
        order = ["import_parse", "await_speaker_confirmation", "generate", "write"]
        for name in order[: order.index(stage)]:
            assert attempts[name] == 1, (name, attempts)  # finished stages are not re-run
    assert list(vault.rglob("*voice-mode-unlabelled.transcript.md"))


def test_pipelines() -> None:
    settings = Settings()
    names = build_pipeline("import", settings, fake=False).names
    assert names == ["import_parse", "await_speaker_confirmation", "generate", "write"]
    assert build_pipeline("import", settings, fake=True).names == names
    with pytest.raises(MM3Error) as info:
        build_pipeline("podcast", settings)
    assert info.value.code == "E_JOB_TYPE"


def test_an_imported_meeting_can_be_renamed_switched_and_regenerated(
    ui: TestClient, vault: Path
) -> None:
    job = upload(ui, UNLABELLED, {"import_confirmed": True, "title": "Garden chat"}).json()
    url, note = written_note(ui, job["id"], vault)
    ws = Workspace(ui, url)
    assert ws.data["can_regenerate"]
    r = ws.task("regenerate", base_sha=ws.sha, section_id="summary")
    assert r.status_code == 200, r.text
    ws = Workspace(ui, url)
    r = ws.task("switch/preview", base_sha=ws.sha, template="action-focused")
    assert r.status_code == 200, r.text
    r = ws.post("switch/apply", token=r.json()["token"])
    assert r.status_code == 200, r.text
    after = parse_note(read_text(note)).note
    assert after.meta.template_id == "action-focused"
    assert after.extra_properties["mm3-source"] == "import"  # kept through the switch
    ws = Workspace(ui, url)
    fields = {"base_sha": ws.sha, "title": "Irrigation plan", "date": "2026-10-21", "time": ""}
    preview = ws.post("retitle/preview", **fields).json()
    r = ws.post("retitle/apply", **fields, digest=preview["digest"])
    assert r.status_code == 200, r.text
    moved = vault / r.json()["note"]
    assert moved.name == "2026-10-21 - Irrigation plan.md"
    companion = moved.with_name(moved.stem + ".transcript.md")
    assert not parse_transcript(read_text(companion)).doc.transcript.timed


def test_mm3_import_command(vault: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MM3_FAKE_PIPELINE", "1")
    monkeypatch.setenv("MM3_FAKE_STAGE_SECONDS", "0")
    out = CliRunner().invoke(
        cli.app,
        [
            "import", str(UNLABELLED), "--vault", str(vault), "--yes",
            "--speaker", "user=Nick", "--speaker", "assistant=Grok", "--title", "Garden",
            "--date", "2026-10-19",
        ],
    )  # fmt: skip
    assert out.exit_code == 0, out.output
    note = vault / "Meetings" / "2026" / "2026-10-19 - Garden.md"
    meta = parse_note(read_text(note)).note.meta
    assert meta.speakers.names == {"SPEAKER_00": "Nick", "SPEAKER_01": "Grok"}


def test_mm3_import_without_yes_and_no_terminal_explains(
    vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MM3_FAKE_PIPELINE", "1")
    monkeypatch.setenv("MM3_FAKE_STAGE_SECONDS", "0")
    out = CliRunner().invoke(cli.app, ["import", str(UNLABELLED), "--vault", str(vault)])
    assert out.exit_code == 1 and "--yes" in out.output
