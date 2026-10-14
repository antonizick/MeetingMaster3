"""Audio retention (R8, ADR-0006): compress at ``written``, expire, prune, pin.

* When a job reaches ``written`` its audio is re-encoded to mono Opus (``audio.opus``) and the
  upload and the WAV are deleted. ``audio_expires_at`` is recorded for the UI.
* The pruner deletes expired, unpinned audio. It applies the **current** retention setting to
  every job (from ``written_at``), so switching to *forever* keeps older audio too.
* Unfinished jobs (failed, cancelled, interrupted, waiting) keep their upload until
  ``audio_retention_days`` after their last change, unless the setting is *forever*.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from meetingmaster3.audio.ingest import encode_opus
from meetingmaster3.config.settings import PrivacySettings, Settings
from meetingmaster3.errors import MM3Error
from meetingmaster3.jobs.files import (
    OPUS_NAME,
    WAV_NAME,
    audio_files,
    biometric_files,
    job_dir,
    resolve_in_job,
)
from meetingmaster3.jobs.models import ACTIVE, JobStatus, iso, utcnow
from meetingmaster3.storage.repositories import JobRecord, JobRepository

log = logging.getLogger(__name__)


def compute_expiry(base: dt.datetime, privacy: PrivacySettings) -> dt.datetime | None:
    """When audio kept since ``base`` expires: ``None`` = never, ``base`` = immediately."""
    if privacy.audio_retention == "forever":
        return None
    if privacy.audio_retention == "delete_after_write":
        return base
    return base + dt.timedelta(days=privacy.audio_retention_days)


def _stale_expiry(job: JobRecord, privacy: PrivacySettings) -> dt.datetime | None:
    if privacy.audio_retention == "forever":
        return None
    return job.updated_at + dt.timedelta(days=privacy.audio_retention_days)


def effective_expiry(job: JobRecord, privacy: PrivacySettings) -> dt.datetime | None:
    """When the pruner will delete this job's audio under the **current** setting.

    ``None`` = never. Ignores pinning (callers check ``job.audio_pinned``). The pruner and the
    review screen's countdown both use this, so they cannot disagree.
    """
    if job.status is JobStatus.WRITTEN and job.written_at is not None:
        return compute_expiry(job.written_at, privacy)
    return _stale_expiry(job, privacy)


RetentionKind = Literal[
    "none",  # no audio left to keep (never had any, or already pruned)
    "kept_pinned",  # the user chose "keep forever"
    "kept_setting",  # privacy.audio_retention is "forever"
    "expires",  # will be deleted on ``expires_at`` (``days_left`` whole days away, at least 1)
    "due",  # past its time; deleted at the next check
]


@dataclass(frozen=True)
class RetentionStatus:
    kind: RetentionKind
    expires_at: dt.datetime | None = None
    days_left: int | None = None

    def to_dict(self) -> dict[str, object]:
        return {"kind": self.kind, "expires_at": iso(self.expires_at), "days_left": self.days_left}


def audio_retention_status(
    job: JobRecord, privacy: PrivacySettings, now: dt.datetime | None = None
) -> RetentionStatus:
    """What the pruner will do with this job's audio, for the UI (R26).

    Days left are whole days rounded up (23 h left = 1 day); 0 means due."""
    now = now or utcnow()
    if job.audio_path is None:
        return RetentionStatus("none")
    if job.audio_pinned:
        return RetentionStatus("kept_pinned")
    expiry = effective_expiry(job, privacy)
    if expiry is None:
        return RetentionStatus("kept_setting")
    if expiry <= now:
        return RetentionStatus("due", expiry, 0)
    return RetentionStatus("expires", expiry, _days_up(expiry - now))


def _days_up(delta: dt.timedelta) -> int:
    return max(1, -(-int(delta.total_seconds()) // 86400))


def playable_audio(folder: Path, job: JobRecord) -> Path | None:
    """The best audio file to play for a job: Opus, then the WAV, then the upload."""
    if job.audio_path is None:
        return None
    for name in (OPUS_NAME, WAV_NAME, job.audio_path):
        path = resolve_in_job(folder, name)
        if path is not None and path.is_file():
            return path
    return None


def audio_expired_error() -> MM3Error:
    return MM3Error(
        "E_AUDIO_EXPIRED",
        "The audio for this meeting was deleted by the retention policy.",
        "The transcript and the note are unaffected. Use Keep forever on a meeting's review page "
        "to keep its audio, or change privacy.audio_retention in the settings.",
        status_code=410,
    )


def finalize_audio(
    jobs: JobRepository,
    jobs_root: Path,
    job: JobRecord,
    settings: Settings,
    written_at: dt.datetime,
) -> JobRecord:
    """Compress the job's audio to Opus, delete the upload and WAV, record the expiry."""
    folder = job_dir(jobs_root, job.id)
    source = playable_audio(folder, job)
    audio_path = job.audio_path
    if source is not None and source.name != OPUS_NAME:
        try:
            encode_opus(
                source,
                folder / OPUS_NAME,
                settings.audio.opus_bitrate_kbps,
                job.duration_seconds,
            )
        except MM3Error as exc:
            # Keep the uncompressed audio rather than lose it; retention still applies.
            log.warning("Opus re-encode failed for job %s: %s", job.id, exc.message)
        else:
            for path in audio_files(folder):
                if path.name != OPUS_NAME:
                    with contextlib.suppress(FileNotFoundError):
                        path.unlink()
            audio_path = OPUS_NAME
    expires = compute_expiry(written_at, settings.privacy) if audio_path else None
    return jobs.update(job.id, audio_path=audio_path, audio_expires_at=expires)


@dataclass(frozen=True)
class PruneItem:
    job_id: str
    title: str
    expired_at: dt.datetime
    files: list[str]
    bytes: int

    def to_dict(self) -> dict[str, object]:
        return {
            "job_id": self.job_id,
            "title": self.title,
            "expired_at": iso(self.expired_at),
            "files": self.files,
            "bytes": self.bytes,
        }


def prune(
    jobs: JobRepository,
    jobs_root: Path,
    settings: Settings,
    *,
    now: dt.datetime | None = None,
    dry_run: bool = False,
) -> list[PruneItem]:
    """Delete expired, unpinned audio and return what was (or, with ``dry_run``, would be)
    removed. Active (queued or running) jobs are never touched."""
    now = now or utcnow()
    pruned: list[PruneItem] = []
    for job in jobs.list_jobs(limit=1_000_000):
        if job.audio_path is None or job.status in ACTIVE:
            continue
        expiry = effective_expiry(job, settings.privacy)
        if (
            job.status is JobStatus.WRITTEN
            and job.written_at is not None
            and expiry != job.audio_expires_at
            and not dry_run
        ):
            jobs.update(job.id, audio_expires_at=expiry)
        if job.audio_pinned or expiry is None or expiry > now:
            continue
        folder = job_dir(jobs_root, job.id)
        files = audio_files(folder)
        size = sum(p.stat().st_size for p in files)
        pruned.append(PruneItem(job.id, job.title, expiry, sorted(p.name for p in files), size))
        if dry_run:
            continue
        for path in files + biometric_files(folder):  # voice embeddings go with the audio
            with contextlib.suppress(FileNotFoundError):
                path.unlink()
        jobs.update(job.id, audio_path=None, audio_pruned_at=now)
        log.info("Pruned audio of job %s (%d files, %d bytes)", job.id, len(files), size)
    return pruned
