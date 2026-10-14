from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Literal

import pytest

from meetingmaster3.audio.ingest import probe
from meetingmaster3.config.settings import PrivacySettings, Settings
from meetingmaster3.errors import MM3Error
from meetingmaster3.jobs import retention
from meetingmaster3.jobs.files import job_dir, new_job_id
from meetingmaster3.jobs.models import JobStatus
from meetingmaster3.storage.db import Database
from meetingmaster3.storage.repositories import JobRepository

from .helpers import (
    Log,
    add_job,
    make_runner,
    make_tone,
    requires_ffmpeg,
    standard_stages,
    wait_status,
)

T0 = dt.datetime(2026, 1, 1, 12, tzinfo=dt.UTC)


@pytest.mark.parametrize(
    ("mode", "days", "expected"),
    [
        ("days", 90, T0 + dt.timedelta(days=90)),
        ("days", 1, T0 + dt.timedelta(days=1)),
        ("forever", 90, None),
        ("delete_after_write", 90, T0),
    ],
)
def test_expiry_maths(mode: str, days: int, expected: dt.datetime | None) -> None:
    privacy = PrivacySettings(audio_retention=mode, audio_retention_days=days)  # type: ignore[arg-type]
    assert retention.compute_expiry(T0, privacy) == expected


def _written_job(
    jobs: JobRepository, root: Path, written: dt.datetime, *, pinned: bool = False
) -> str:
    job_id = new_job_id()
    folder = job_dir(root, job_id, create=True)
    (folder / "audio.opus").write_bytes(b"x" * 100)
    (folder / "transcript.json").write_text("{}")
    jobs.create(job_id, stages=["a"], audio_path="audio.opus", status=JobStatus.RUNNING)
    jobs.set_status(job_id, JobStatus.WRITTEN, written_at=written, audio_pinned=pinned)
    return job_id


def test_prune_respects_expiry_pin_and_dry_run(tmp_path: Path) -> None:
    db = Database.open(tmp_path / "mm3.db")
    jobs, root = JobRepository(db), tmp_path / "jobs"
    settings = Settings()
    now = T0 + dt.timedelta(days=100)
    old = _written_job(jobs, root, T0)
    pinned = _written_job(jobs, root, T0, pinned=True)
    fresh = _written_job(jobs, root, now - dt.timedelta(days=5))

    dry = retention.prune(jobs, root, settings, now=now, dry_run=True)
    assert [i.job_id for i in dry] == [old]
    assert dry[0].files == ["audio.opus"] and dry[0].bytes == 100
    assert (job_dir(root, old) / "audio.opus").exists()  # dry run deletes nothing
    assert jobs.get(old).audio_path == "audio.opus"

    done = retention.prune(jobs, root, settings, now=now)
    assert [i.job_id for i in done] == [old]
    assert not (job_dir(root, old) / "audio.opus").exists()
    assert (job_dir(root, old) / "transcript.json").exists()  # only audio is pruned
    job = jobs.get(old)
    assert job.audio_path is None and job.audio_pruned_at == now
    assert jobs.get(pinned).audio_path == "audio.opus"
    assert jobs.get(fresh).audio_path == "audio.opus"
    assert jobs.get(fresh).audio_expires_at == now - dt.timedelta(days=5) + dt.timedelta(days=90)
    assert retention.prune(jobs, root, settings, now=now) == []  # idempotent

    # Switching to "forever" keeps everything; the recorded expiry is cleared.
    settings.privacy.audio_retention = "forever"
    assert retention.prune(jobs, root, settings, now=now + dt.timedelta(days=999)) == []
    assert jobs.get(fresh).audio_expires_at is None


def test_stale_unfinished_jobs_are_pruned_too(tmp_path: Path) -> None:
    db = Database.open(tmp_path / "mm3.db")
    jobs, root = JobRepository(db), tmp_path / "jobs"
    job_id = new_job_id()
    folder = job_dir(root, job_id, create=True)
    (folder / "original.m4a").write_bytes(b"abc")
    (folder / "audio.wav").write_bytes(b"abcd")
    (folder / "speaker_embeddings.json").write_text("{}")  # never confirmed (S7)
    jobs.create(job_id, stages=["a"], audio_path="original.m4a", status=JobStatus.RUNNING)
    jobs.set_status(job_id, JobStatus.FAILED)
    now = jobs.get(job_id).updated_at
    settings = Settings()
    assert retention.prune(jobs, root, settings, now=now + dt.timedelta(days=89)) == []
    items = retention.prune(jobs, root, settings, now=now + dt.timedelta(days=91))
    assert items[0].files == ["audio.wav", "original.m4a"] and items[0].bytes == 7
    assert not (folder / "speaker_embeddings.json").exists()  # voice data goes with the audio
    # Active jobs are never touched.
    active = new_job_id()
    job_dir(root, active, create=True)
    jobs.create(active, stages=["a"], audio_path="original.m4a")
    assert retention.prune(jobs, root, settings, now=now + dt.timedelta(days=9999)) == []


@requires_ffmpeg
async def test_written_job_keeps_opus_only(tmp_path: Path) -> None:
    runner = make_runner(tmp_path, standard_stages(Log()))
    await runner.start(prune=False)
    try:
        job_id = add_job(runner)
        folder = job_dir(runner.jobs_root, job_id)
        make_tone(folder / "original.wav", 3.0)
        make_tone(folder / "audio.wav", 3.0, channels=1)
        await wait_status(runner, job_id, JobStatus.WAITING_FOR_INPUT)
        runner.submit_input(job_id, {"speakers": {"SPEAKER_00": "A"}})
        await wait_status(runner, job_id, JobStatus.WRITTEN)
        job = runner.jobs.get(job_id)
        assert job.audio_path == "audio.opus"
        assert not (folder / "original.wav").exists() and not (folder / "audio.wav").exists()
        info = probe(folder / "audio.opus")
        assert info.codec == "opus" and info.channels == 1
        assert abs(info.duration_seconds - 3.0) < 0.2
        assert job.written_at is not None
        assert job.audio_expires_at == job.written_at + dt.timedelta(days=90)
        assert runner.audio_file(job_id).name == "audio.opus"
    finally:
        await runner.stop()


@requires_ffmpeg
async def test_delete_after_write_prunes_immediately(tmp_path: Path) -> None:
    settings = Settings()
    settings.privacy.audio_retention = "delete_after_write"
    runner = make_runner(tmp_path, standard_stages(Log()), settings)
    await runner.start(prune=False)
    try:
        job_id = add_job(runner)
        make_tone(job_dir(runner.jobs_root, job_id) / "original.wav", 1.0)
        await wait_status(runner, job_id, JobStatus.WAITING_FOR_INPUT)
        runner.submit_input(job_id, {"speakers": {"SPEAKER_00": "A"}})
        await wait_status(runner, job_id, JobStatus.WRITTEN)
        await __import__("asyncio").sleep(0.1)
        job = runner.jobs.get(job_id)
        assert job.audio_path is None and job.audio_pruned_at is not None
        with pytest.raises(MM3Error) as exc:
            runner.audio_file(job_id)
        assert exc.value.code == "E_AUDIO_EXPIRED" and exc.value.status_code == 410
        with pytest.raises(MM3Error):
            runner.set_pinned(job_id, True)  # nothing left to pin
    finally:
        await runner.stop()


async def test_opus_failure_keeps_audio(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*args: object, **kwargs: object) -> Path:
        raise MM3Error("E_AUDIO_DECODE", "nope", "")

    monkeypatch.setattr(retention, "encode_opus", broken)
    runner = make_runner(tmp_path, standard_stages(Log()))
    await runner.start(prune=False)
    try:
        job_id = add_job(runner)
        await wait_status(runner, job_id, JobStatus.WAITING_FOR_INPUT)
        runner.submit_input(job_id, {"speakers": {"SPEAKER_00": "A"}})
        await wait_status(runner, job_id, JobStatus.WRITTEN)
        job = runner.jobs.get(job_id)
        assert job.audio_path == "original.wav" and job.audio_expires_at is not None
    finally:
        await runner.stop()


# -- the review screen's countdown (R26): same rule as the pruner --------------------------------


def _privacy(
    mode: Literal["forever", "days", "delete_after_write"] = "days", days: int = 90
) -> PrivacySettings:
    return PrivacySettings(audio_retention=mode, audio_retention_days=days)


def _status_job(
    tmp_path: Path, written: dt.datetime | None, *, pinned: bool = False
) -> tuple[JobRepository, Path, str]:
    db = Database.open(tmp_path / "mm3.db")
    jobs, root = JobRepository(db), tmp_path / "jobs"
    if written is not None:
        job_id = _written_job(jobs, root, written, pinned=pinned)
    else:
        job_id = new_job_id()
        job_dir(root, job_id, create=True)
        jobs.create(job_id, stages=["a"], audio_path="original.m4a", status=JobStatus.RUNNING)
        jobs.set_status(job_id, JobStatus.FAILED, audio_pinned=pinned)
    return jobs, root, job_id


@pytest.mark.parametrize(
    ("offset", "kind", "days"),
    [
        (dt.timedelta(days=90), "expires", 90),  # exactly 90 days left
        (dt.timedelta(days=90, seconds=-1), "expires", 90),  # rounded up
        (dt.timedelta(days=1, seconds=1), "expires", 2),
        (dt.timedelta(days=1), "expires", 1),
        (dt.timedelta(hours=1), "expires", 1),  # under a day is still "1 day", never 0
        (dt.timedelta(0), "due", 0),  # the pruner deletes at expiry <= now
        (dt.timedelta(days=-3), "due", 0),
    ],
)
def test_days_left_rounding_and_boundaries(
    tmp_path: Path, offset: dt.timedelta, kind: str, days: int
) -> None:
    jobs, _root, job_id = _status_job(tmp_path, T0)
    now = T0 + dt.timedelta(days=90) - offset
    status = retention.audio_retention_status(jobs.get(job_id), _privacy(), now)
    assert (status.kind, status.days_left) == (kind, days)


def test_status_for_every_setting_and_pin(tmp_path: Path) -> None:
    jobs, _root, job_id = _status_job(tmp_path, T0)
    job = jobs.get(job_id)
    now = T0 + dt.timedelta(days=10)
    assert retention.audio_retention_status(job, _privacy("forever"), now).kind == "kept_setting"
    assert retention.audio_retention_status(job, _privacy("delete_after_write"), now).kind == "due"
    pinned = _status_job(tmp_path / "p", T0, pinned=True)
    pinned_job = pinned[0].get(pinned[2])
    for mode in ("days", "forever", "delete_after_write"):
        assert (
            retention.audio_retention_status(pinned_job, _privacy(mode), now).kind == "kept_pinned"
        )
    # Unfinished jobs count from their last change, like the pruner does.
    unfinished = _status_job(tmp_path / "u", None)
    job_u = unfinished[0].get(unfinished[2])
    status = retention.audio_retention_status(job_u, _privacy(), job_u.updated_at)
    assert status.kind == "expires" and status.days_left == 90
    # No audio left (pruned): nothing to keep.
    jobs.update(job_id, audio_path=None)
    assert retention.audio_retention_status(jobs.get(job_id), _privacy(), now).kind == "none"


@pytest.mark.parametrize("mode", ["days", "forever", "delete_after_write"])
@pytest.mark.parametrize("pinned", [False, True])
@pytest.mark.parametrize("day", [0, 30, 89, 90, 91, 400])
def test_status_agrees_with_the_pruner(
    tmp_path: Path, mode: Literal["forever", "days", "delete_after_write"], pinned: bool, day: int
) -> None:
    """The line shown on the review screen never disagrees with what prune() will do."""
    jobs, root, job_id = _status_job(tmp_path, T0, pinned=pinned)
    settings = Settings()
    settings.privacy = _privacy(mode)
    now = T0 + dt.timedelta(days=day)
    status = retention.audio_retention_status(jobs.get(job_id), settings.privacy, now)
    would_delete = bool(retention.prune(jobs, root, settings, now=now, dry_run=True))
    assert would_delete == (status.kind == "due")
    # Changing the setting changes the answer for both, together.
    settings.privacy = _privacy("days", 30)
    status = retention.audio_retention_status(jobs.get(job_id), settings.privacy, now)
    would_delete = bool(retention.prune(jobs, root, settings, now=now, dry_run=True))
    assert would_delete == (status.kind == "due")
    if status.kind == "expires":
        assert status.expires_at == T0 + dt.timedelta(days=30)
