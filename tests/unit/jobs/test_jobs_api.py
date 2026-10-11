from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from meetingmaster3.app import create_app
from meetingmaster3.config.paths import resolve_paths
from meetingmaster3.config.settings import Settings

from .helpers import make_tone, requires_ffmpeg

pytestmark = requires_ffmpeg


@pytest.fixture
def settings() -> Settings:
    return Settings()


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


def upload(api: TestClient, path: Path, options: dict[str, object] | None = None):  # type: ignore[no-untyped-def]
    with path.open("rb") as fh:
        return api.post(
            "/api/jobs",
            files={"file": (path.name, fh, "audio/mp4")},
            data={"options": json.dumps(options or {})},
        )


def wait(api: TestClient, job_id: str, status: str, timeout: float = 10) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job: dict[str, object] = api.get(f"/api/jobs/{job_id}").json()
        if job["status"] == status:
            return job
        time.sleep(0.02)
    raise AssertionError(f"{job_id} never reached {status}: {job}")


def sse(text: str) -> list[tuple[str, dict[str, object]]]:
    events = []
    for block in text.split("\n\n"):
        lines = [ln for ln in block.splitlines() if ln and not ln.startswith(":")]
        if not lines:
            continue
        name = next(ln[7:] for ln in lines if ln.startswith("event: "))
        data = json.loads(next(ln[6:] for ln in lines if ln.startswith("data: ")))
        events.append((name, data))
    return events


def test_upload_to_waiting_then_mapping_finishes(api: TestClient, tone: Path) -> None:
    r = upload(api, tone, {"diarize": True})
    assert r.status_code == 201, r.text
    job = r.json()
    assert job["title"] == "Product Sync" and job["meeting_date"] == "2026-10-11"
    assert job["source_filename"] == tone.name and abs(job["duration_seconds"] - 2.0) < 0.1
    assert [s["stage"] for s in job["stages"]][:2] == ["ingest", "transcribe"]
    folder = resolve_paths().jobs_dir / job["id"]
    assert (folder / "original.m4a").is_file()

    waiting = wait(api, job["id"], "waiting_for_input")
    question = waiting["waiting_for"]
    assert question["kind"] == "speaker_confirmation"  # type: ignore[index]
    assert [s["label"] for s in question["speakers"]] == ["SPEAKER_00", "SPEAKER_01"]  # type: ignore[index]

    # Replay: a client connecting now gets the current state first.
    result: dict[str, str] = {}

    def listen() -> None:
        result["text"] = api.get(f"/api/jobs/{job['id']}/events").text

    listener = threading.Thread(target=listen)
    listener.start()
    time.sleep(0.3)
    r = api.post(
        f"/api/jobs/{job['id']}/input",
        json={"speakers": {"SPEAKER_00": "Alice", "SPEAKER_01": {"name": "Bob"}}},
    )
    assert r.status_code == 200, r.text
    listener.join(10)
    events = sse(result["text"])
    assert events[0][0] == "snapshot" and events[0][1]["status"] == "waiting_for_input"
    seqs = [e[1]["seq"] for e in events]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    completed = [e[1]["stage"] for e in events if e[1].get("status") == "completed"]
    assert completed == ["await_speaker_confirmation", "generate", "write"]
    assert events[-1][0] == "job" and events[-1][1]["status"] == "written"

    done = api.get(f"/api/jobs/{job['id']}").json()
    assert done["status"] == "written" and done["audio"]["expires_at"]
    assert "Alice, Bob" in (folder / "notes.draft.md").read_text()
    assert not (folder / "original.m4a").exists() and (folder / "audio.opus").is_file()

    # Audio with HTTP Range.
    r = api.get(f"/api/jobs/{job['id']}/audio", headers={"Range": "bytes=0-9"})
    assert r.status_code == 206 and len(r.content) == 10
    assert r.headers["content-type"] == "audio/ogg"

    # A finished job's SSE stream is just the snapshot.
    events = sse(api.get(f"/api/jobs/{job['id']}/events").text)
    assert [e[0] for e in events] == ["snapshot"]

    listing = api.get("/api/jobs", params={"status": "written"}).json()["jobs"]
    assert [j["id"] for j in listing] == [job["id"]]
    assert api.get("/api/jobs", params={"status": "failed"}).json()["jobs"] == []


def test_sse_streams_live_progress_in_order(
    api: TestClient, tone: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MM3_FAKE_STAGE_SECONDS", "0.1")
    job_id = upload(api, tone).json()["id"]
    result: dict[str, str] = {}
    t = threading.Thread(
        target=lambda: result.update(text=api.get(f"/api/jobs/{job_id}/events").text)
    )
    t.start()
    wait(api, job_id, "waiting_for_input")
    time.sleep(0.2)
    api.post(f"/api/jobs/{job_id}/cancel")  # the stream stays open while waiting; end it
    t.join(10)
    events = sse(result["text"])
    assert events[0][0] == "snapshot"
    seqs = [e[1]["seq"] for e in events]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    stage_events = [e[1] for e in events if e[0] == "stage"]
    completed = [e["stage"] for e in stage_events if e["status"] == "completed"]
    assert completed == ["ingest", "transcribe", "align", "diarize", "speaker_suggest"]
    fractions = [e["fraction"] for e in stage_events if e["stage"] == "diarize" and e["fraction"]]
    assert fractions == sorted(fractions) and fractions[-1] == 1.0
    jobs = [e[1]["status"] for e in events if e[0] == "job"]
    assert jobs[-2:] == ["waiting_for_input", "cancelled"]


def test_cancel_resume_delete_pin(api: TestClient, tone: Path) -> None:
    job_id = upload(api, tone).json()["id"]
    wait(api, job_id, "waiting_for_input")
    assert api.post(f"/api/jobs/{job_id}/pin").json()["audio"]["pinned"] is True
    assert api.post(f"/api/jobs/{job_id}/cancel").json()["status"] == "cancelled"
    assert api.delete(f"/api/jobs/{job_id}").json()["code"] == "E_JOB_PINNED"
    assert api.post(f"/api/jobs/{job_id}/unpin").json()["audio"]["pinned"] is False
    r = api.post(f"/api/jobs/{job_id}/resume", json={"overrides": {"model": "medium"}})
    assert r.status_code == 200 and r.json()["options"]["model"] == "medium"
    wait(api, job_id, "waiting_for_input")
    assert api.post(f"/api/jobs/{job_id}/resume").status_code == 409
    assert api.post(f"/api/jobs/{job_id}/resume", content=b"[1]").status_code == 400
    api.post(f"/api/jobs/{job_id}/cancel")
    assert api.delete(f"/api/jobs/{job_id}").json() == {"deleted": job_id}
    assert api.get(f"/api/jobs/{job_id}").status_code == 404
    assert not (resolve_paths().jobs_dir / job_id).exists()


def test_state_changing_routes_need_csrf(api: TestClient, tone: Path) -> None:
    job_id = upload(api, tone).json()["id"]
    token = api.headers.pop("X-CSRF-Token")
    for method, url in [
        ("POST", "/api/jobs"),
        ("POST", f"/api/jobs/{job_id}/cancel"),
        ("POST", f"/api/jobs/{job_id}/resume"),
        ("POST", f"/api/jobs/{job_id}/input"),
        ("POST", f"/api/jobs/{job_id}/pin"),
        ("DELETE", f"/api/jobs/{job_id}"),
    ]:
        assert api.request(method, url).status_code == 403, url
    api.headers["X-CSRF-Token"] = token


@pytest.mark.parametrize("settings", [Settings(audio={"max_upload_mb": 1})])  # type: ignore[arg-type]
def test_upload_size_limit(api: TestClient, tmp_path: Path) -> None:
    big = tmp_path / "big.wav"
    big.write_bytes(b"\0" * (3 * 1024 * 1024))
    r = upload(api, big)
    assert r.status_code == 413 and r.json()["code"] == "E_UPLOAD_TOO_LARGE"
    # Streaming check (no Content-Length): a chunked body is cut off at the limit too.
    body = b'--b\r\nContent-Disposition: form-data; name="file"; filename="x.wav"\r\n\r\n'

    def chunks() -> Iterator[bytes]:
        yield body
        for _ in range(3):
            yield b"\0" * (1024 * 1024)
        yield b"\r\n--b--\r\n"

    r = api.post(
        "/api/jobs", content=chunks(), headers={"Content-Type": "multipart/form-data; boundary=b"}
    )
    assert r.status_code == 413
    assert list(resolve_paths().jobs_dir.iterdir()) == []


def test_rejects_non_audio_and_bad_requests(api: TestClient, tmp_path: Path, tone: Path) -> None:
    text = tmp_path / "notes.m4a"
    text.write_text("not audio\n" * 100)
    r = upload(api, text)
    assert r.status_code == 422 and r.json()["code"] == "E_AUDIO_UNSUPPORTED"
    assert r.json()["hint"]
    assert api.post("/api/jobs", data={"x": "1"}).json()["code"] == "E_UPLOAD_INVALID"
    assert api.post("/api/jobs", content=b"raw").status_code == 400
    empty = tmp_path / "empty.wav"
    empty.write_bytes(b"")
    assert upload(api, empty).json()["code"] == "E_UPLOAD_INVALID"
    with tone.open("rb") as fh:
        r = api.post("/api/jobs", files={"file": ("a.m4a", fh)}, data={"options": "{nope"})
    assert r.json()["code"] == "E_UPLOAD_INVALID"
    with tone.open("rb") as fh:
        r = api.post(
            "/api/jobs", files={"file": ("a.m4a", fh)}, data={"options": '{"min_speakers": 0}'}
        )
    assert r.status_code == 422 and r.json()["code"] == "E_OPTIONS_INVALID"
    assert list(resolve_paths().jobs_dir.iterdir()) == []  # nothing left behind


def test_client_filename_never_becomes_a_path(api: TestClient, tone: Path) -> None:
    with tone.open("rb") as fh:
        r = api.post("/api/jobs", files={"file": ("../../../../tmp/evil.m4a", fh)})
    job = r.json()
    assert r.status_code == 201 and job["source_filename"] == "evil.m4a"
    folder = resolve_paths().jobs_dir / job["id"]
    assert (folder / "original.m4a").is_file()
    assert not Path("/tmp/evil.m4a").exists()  # noqa: S108


def test_job_ids_are_validated(api: TestClient) -> None:
    for bad in ["..%2F..%2Fetc", "abc", "6f1c1c4e-2b7a-1c55-9d43-0a1b2c3d4e5f"]:
        r = api.get(f"/api/jobs/{bad}")
        assert r.status_code == 404
    missing = "6f1c1c4e-2b7a-4c55-9d43-0a1b2c3d4e5f"
    assert api.get(f"/api/jobs/{missing}").json()["code"] == "E_JOB_NOT_FOUND"
    assert api.get(f"/api/jobs/{missing}/events").status_code == 404
    assert api.get(f"/api/jobs/{missing}/audio").status_code == 404


def test_runner_down_without_lifespan() -> None:
    client = TestClient(create_app(Settings()), base_url="http://localhost")
    r = client.get("/api/jobs")
    assert r.status_code == 503 and r.json()["code"] == "E_RUNNER_DOWN"
