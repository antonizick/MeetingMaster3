"""Exporting a meeting and all app data."""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from meetingmaster3 import exporting
from meetingmaster3.domain.transcript import Segment, SpeakerMap, Transcript
from meetingmaster3.errors import MM3Error
from meetingmaster3.markdown.transcript_format import build_companion, render_transcript
from meetingmaster3.speakers.store import VoiceprintStore

NOTE = "Meetings/2026/2026-10-11 - Product Sync.md"
TRANSCRIPT = "Meetings/2026/2026-10-11 - Product Sync.transcript.md"


def make_transcript_text() -> str:
    transcript = Transcript(
        segments=[
            Segment(id=0, start=1.0, end=4.0, speaker_label="SPEAKER_00", text="Good morning."),
            Segment(id=1, start=65.0, end=70.0, speaker_label="SPEAKER_01", text="Shall we start?"),
        ],
        language="en",
        duration=70.0,
        diarized=True,
    )
    speakers = SpeakerMap(names={"SPEAKER_00": "Alice", "SPEAKER_01": "Bob"})
    doc = build_companion(uuid.uuid4(), "Product Sync", transcript, speakers, note_ref="n")
    return render_transcript(doc)


@pytest.fixture
def written(vault: Path) -> Path:
    folder = vault / "Meetings" / "2026"
    folder.mkdir(parents=True)
    (folder / "2026-10-11 - Product Sync.md").write_text("---\nmm3-id: x\n---\n# Note\n")
    (folder / "2026-10-11 - Product Sync.transcript.md").write_text(make_transcript_text())
    return vault


def test_plain_text_transcript(written: Path) -> None:
    text = exporting.transcript_to_text((written / TRANSCRIPT).read_text())
    assert text == "[00:00:01] Alice: Good morning.\n[00:01:05] Bob: Shall we start?\n"
    assert exporting.transcript_to_text("not a transcript") == "not a transcript"


def test_locate_refuses_escapes_and_non_notes(written: Path) -> None:
    for bad in ("../secret.md", "/etc/passwd", NOTE.replace(".md", ".txt"), TRANSCRIPT):
        with pytest.raises(MM3Error):
            exporting.locate(written, bad)
    with pytest.raises(MM3Error):
        exporting.locate(written, "Meetings/2026/missing.md")


def test_export_meeting_api(ui: TestClient, written: Path) -> None:
    note = ui.get("/api/export/meeting", params={"note": NOTE, "kind": "note"})
    assert note.status_code == 200 and note.text.endswith("# Note\n")
    assert "attachment" in note.headers["content-disposition"]
    txt = ui.get("/api/export/meeting", params={"note": NOTE, "kind": "txt"})
    assert txt.text.startswith("[00:00:01] Alice:") and txt.headers["content-type"].startswith(
        "text/plain"
    )
    tr = ui.get("/api/export/meeting", params={"note": NOTE, "kind": "transcript"})
    assert "mm3-version" in tr.text
    z = zipfile.ZipFile(io.BytesIO(ui.get("/api/export/meeting", params={"note": NOTE}).content))
    assert sorted(z.namelist()) == [
        "2026-10-11 - Product Sync.md",
        "2026-10-11 - Product Sync.transcript.md",
        "2026-10-11 - Product Sync.transcript.txt",
    ]
    assert ui.get("/api/export/meeting", params={"note": "../x.md"}).status_code == 400
    assert ui.get("/api/export/meeting", params={"note": NOTE, "kind": "pdf"}).status_code == 422


def test_note_without_companion(ui: TestClient, written: Path) -> None:
    (written / TRANSCRIPT).unlink()
    assert ui.get("/api/export/meeting", params={"note": NOTE, "kind": "txt"}).status_code == 404
    z = zipfile.ZipFile(io.BytesIO(ui.get("/api/export/meeting", params={"note": NOTE}).content))
    assert z.namelist() == ["2026-10-11 - Product Sync.md"]


def test_job_export_includes_audio_when_retained(ui: TestClient, written: Path) -> None:
    from meetingmaster3.storage.repositories import JobRepository

    runner = ui.app.state.runner  # type: ignore[attr-defined]
    job = JobRepository(runner.db).create(
        str(uuid.uuid4()), stages=["write"], source_filename="a.opus"
    )
    folder = runner.jobs_root / job.id
    folder.mkdir(parents=True)
    (folder / "audio.opus").write_bytes(b"OPUSDATA")
    JobRepository(runner.db).update(job.id, audio_path="audio.opus")
    (folder / "written.json").write_text(
        json.dumps({"mm3_id": "x", "note_relative": NOTE, "template": "t"})
    )
    z = zipfile.ZipFile(io.BytesIO(ui.get(f"/api/jobs/{job.id}/export").content))
    assert "2026-10-11 - Product Sync.opus" in z.namelist()
    (folder / "audio.opus").unlink()  # expired
    z = zipfile.ZipFile(io.BytesIO(ui.get(f"/api/jobs/{job.id}/export").content))
    assert all(not n.endswith(".opus") for n in z.namelist())
    assert ui.get(f"/api/jobs/{uuid.uuid4()}/export").status_code in (404,)


def test_export_all_has_no_secrets_audio_or_voiceprints(ui: TestClient) -> None:
    settings = ui.app.state.settings  # type: ignore[attr-defined]
    ui.post("/settings/transcription", data={"secrets.hf_token": "hf_EXPORTSECRET"})
    ui.post("/settings/llm/save", data={"orig_name": "", "name": "cloud", "kind": "openrouter",
                                        "api_key": "sk-EXPORTSECRET"})  # fmt: skip
    runner = ui.app.state.runner  # type: ignore[attr-defined]
    VoiceprintStore(runner.db, enabled=True).create_person("Ana Voiceprint")
    from meetingmaster3.storage.repositories import JobRepository

    job = JobRepository(runner.db).create(
        str(uuid.uuid4()), stages=["write"], source_filename="a.opus"
    )
    folder = runner.jobs_root / job.id
    folder.mkdir(parents=True)
    (folder / "transcript.json").write_text('{"ok": true}')
    (folder / "audio.opus").write_bytes(b"AUDIO")
    ui.post("/api/feedback", json={"mm3_id": "m", "rating_kind": "stars", "value": 3})

    r = ui.get("/api/export/all")
    assert r.headers["content-type"] == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = z.namelist()
    assert f"jobs/{job.id}/transcript.json" in names
    assert not any(n.endswith(".opus") for n in names)
    blob = b"".join(z.read(n) for n in names)
    assert b"hf_EXPORTSECRET" not in blob and b"sk-EXPORTSECRET" not in blob
    assert b"Ana Voiceprint" not in blob
    tables = {n.split("/")[-1] for n in names if n.startswith("database/")}
    assert tables == {"jobs.json", "job_stages.json", "recent_meetings.json", "feedback.json"}
    assert json.loads(z.read("database/feedback.json"))[0]["value"] == 3
    assert json.loads(z.read("settings.json"))["secrets"]["hf_token"] == "********"
    assert settings.secrets.hf_token is not None
