from __future__ import annotations

import threading
import wave
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from meetingmaster3.audio import ingest
from meetingmaster3.audio.ingest import (
    UploadTooLarge,
    display_filename,
    encode_opus,
    normalise,
    probe,
    safe_extension,
    save_stream,
)
from meetingmaster3.audio.stage import IngestStage
from meetingmaster3.config.settings import Settings
from meetingmaster3.errors import MM3Error
from meetingmaster3.jobs.files import audio_files, check_job_id, job_dir, new_job_id, resolve_in_job
from meetingmaster3.jobs.models import JobStatus
from meetingmaster3.jobs.stage import CancelToken, StageContext
from meetingmaster3.storage.db import Database
from meetingmaster3.storage.repositories import JobRepository

from .helpers import make_tone, requires_ffmpeg


@pytest.mark.parametrize(
    ("name", "ext"),
    [
        ("meeting.M4A", "m4a"),
        ("a.b.mp3", "mp3"),
        ("../../etc/passwd", "bin"),
        ("..\\..\\evil.wav", "wav"),
        ("noext", "bin"),
        ("x.exe", "bin"),
        ("", "bin"),
        (None, "bin"),
    ],
)
def test_safe_extension(name: str | None, ext: str) -> None:
    assert safe_extension(name) == ext


def test_display_filename_strips_paths_and_controls() -> None:
    assert display_filename("../x/Sync\x00\n.m4a") == "Sync.m4a"
    assert display_filename(None) == ""


async def _chunks(*parts: bytes) -> AsyncIterator[bytes]:
    for p in parts:
        yield p


async def test_save_stream_enforces_limit_and_cleans_up(tmp_path: Path) -> None:
    dest = tmp_path / "up.bin"
    assert await save_stream(_chunks(b"ab", b"cd"), dest, 4) == 4
    assert dest.read_bytes() == b"abcd" and (dest.stat().st_mode & 0o777) == 0o600
    big = tmp_path / "big.bin"
    with pytest.raises(UploadTooLarge) as exc:
        await save_stream(_chunks(b"abc", b"de"), big, 4)
    assert exc.value.status_code == 413 and not big.exists()
    with pytest.raises(FileExistsError):
        await save_stream(_chunks(b"x"), dest, 4)  # never overwrites


def test_missing_ffmpeg_has_install_hint(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(ingest.shutil, "which", lambda name: None)
    with pytest.raises(MM3Error) as exc:
        probe(tmp_path / "x.wav")
    assert exc.value.code == "E_FFMPEG_MISSING" and "pacman" in exc.value.hint


@requires_ffmpeg
def test_probe_rejects_non_audio(tmp_path: Path) -> None:
    text = tmp_path / "notes.mp3"
    text.write_text("this is not audio at all\n" * 50)
    with pytest.raises(MM3Error) as exc:
        probe(text)
    assert exc.value.code == "E_AUDIO_UNSUPPORTED" and exc.value.status_code == 422


@requires_ffmpeg
def test_probe_rejects_video_without_audio(tmp_path: Path) -> None:
    import shutil
    import subprocess

    video = tmp_path / "silent.mp4"
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    args = "-nostdin -loglevel error -f lavfi -i color=c=black:s=32x32:d=1 -pix_fmt yuv420p"
    subprocess.run([ffmpeg, *args.split(), str(video)], check=True)  # noqa: S603
    with pytest.raises(MM3Error, match="no audio track"):
        probe(video)


@requires_ffmpeg
def test_normalise_tone_to_16k_mono_wav(tmp_path: Path) -> None:
    src = make_tone(tmp_path / "tone.m4a", 2.0, channels=2)
    info = probe(src)
    assert info.channels == 2 and abs(info.duration_seconds - 2.0) < 0.1
    assert info.to_dict()["codec"] == info.codec
    dst = normalise(src, tmp_path / "audio.wav", info.duration_seconds)
    with wave.open(str(dst)) as w:
        assert (w.getnchannels(), w.getframerate(), w.getsampwidth()) == (1, 16000, 2)
        assert abs(w.getnframes() / 16000 - 2.0) < 0.1
    assert not list(tmp_path.glob(".*.part"))


@requires_ffmpeg
def test_encode_opus_from_tone(tmp_path: Path) -> None:
    src = make_tone(tmp_path / "tone.wav", 2.0)
    dst = encode_opus(src, tmp_path / "audio.opus", 24)
    info = probe(dst)
    assert (info.codec, info.channels) == ("opus", 1)


@requires_ffmpeg
def test_decode_failure_is_reported(tmp_path: Path) -> None:
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"RIFF\x00\x00\x00\x00WAVEfmt garbage")
    with pytest.raises(MM3Error) as exc:
        normalise(bad, tmp_path / "out.wav", 1.0)
    assert exc.value.code == "E_AUDIO_DECODE"
    assert not (tmp_path / "out.wav").exists() and not list(tmp_path.glob(".*.part"))


def test_subprocess_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    def slow(*args: object, **kwargs: object) -> None:
        raise subprocess.TimeoutExpired("ffprobe", 1)

    monkeypatch.setattr(ingest.subprocess, "run", slow)
    with pytest.raises(MM3Error) as exc:
        ingest._run(["ffprobe"], 1, "Probing")
    assert exc.value.code == "E_AUDIO_TIMEOUT"


@requires_ffmpeg
def test_ingest_stage(tmp_path: Path) -> None:
    db = Database.open(tmp_path / "mm3.db")
    job_id = new_job_id()
    folder = job_dir(tmp_path / "jobs", job_id, create=True)
    make_tone(folder / "original.m4a", 1.0)
    job = JobRepository(db).create(
        job_id, stages=["ingest"], audio_path="original.m4a", status=JobStatus.RUNNING
    )
    messages: list[str] = []
    ctx = StageContext(
        job=job, stage="ingest", job_dir=folder, settings=Settings(), options={},
        artifacts={}, attempt=1, token=CancelToken(),
        _progress=lambda f, m, e: messages.append(m),
    )  # fmt: skip
    out = IngestStage().run(ctx)
    assert out == folder / "audio.wav" and out.exists()
    assert messages[-1].startswith("Audio ready")
    assert {p.name for p in audio_files(folder)} == {"original.m4a", "audio.wav"}

    gone = JobRepository(db).update(job_id, audio_path="../escape.wav")
    ctx.job = gone
    with pytest.raises(MM3Error) as exc:
        IngestStage().run(ctx)
    assert exc.value.code == "E_AUDIO_MISSING"


def test_job_paths_are_confined(tmp_path: Path) -> None:
    root = tmp_path / "jobs"
    for bad in ["../x", "..", "abc", "6f1c1c4e-2b7a-1c55-9d43-0a1b2c3d4e5f", "", "/etc"]:
        with pytest.raises(MM3Error):
            check_job_id(bad)
        with pytest.raises(MM3Error):
            job_dir(root, bad)
    job_id = new_job_id()
    folder = job_dir(root, job_id, create=True)
    assert folder.parent == root and (folder.stat().st_mode & 0o777) == 0o700
    assert resolve_in_job(folder, "audio.wav") == folder / "audio.wav"
    for bad in ["../x", "a/b", "..", ".", None, "", "a\\b"]:
        assert resolve_in_job(folder, bad) is None
    # A symlinked job folder pointing outside the data folder is refused.
    outside = tmp_path / "outside"
    outside.mkdir()
    other = new_job_id()
    (root / other).symlink_to(outside)
    with pytest.raises(MM3Error) as exc:
        job_dir(root, other)
    assert exc.value.code == "E_JOB_PATH"
    # A symlinked artifact name inside the folder that escapes is refused.
    (folder / "link.json").symlink_to(outside / "x.json")
    assert resolve_in_job(folder, "link.json") is None


def test_cancel_token_and_context_helpers(tmp_path: Path) -> None:
    token = CancelToken()
    assert token.wait(0.01) is False
    threading.Timer(0.01, token.cancel).start()
    assert token.wait(2) is True and token.cancelled and not token.shutdown
    token.cancel(shutdown=True)
    assert token.shutdown

    db = Database.open(tmp_path / "mm3.db")
    job = JobRepository(db).create(new_job_id(), stages=["s"])
    ctx = StageContext(
        job=job, stage="s", job_dir=tmp_path, settings=Settings(), options={}, artifacts={},
        attempt=1, token=CancelToken(), _progress=lambda f, m, e: None,
    )  # fmt: skip
    for bad in ["", "a/b", "..", "."]:
        with pytest.raises(ValueError, match="bare file name"):
            ctx.artifact(bad)
    assert ctx.input() is None
    ctx.progress(5.0)  # clamped, no error
    ctx.token.cancel()
    with pytest.raises(Exception, match=job.id):
        ctx.sleep(1)
