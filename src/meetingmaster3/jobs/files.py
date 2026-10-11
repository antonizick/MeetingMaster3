"""Job ids and job folders (``<data>/jobs/<job-id>/``), with path confinement (S4)."""

from __future__ import annotations

import re
import shutil
import uuid
from pathlib import Path

from meetingmaster3.errors import MM3Error
from meetingmaster3.vault.paths import is_inside

JOB_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")

#: Audio files a job folder may hold (the upload is ``original.<ext>``).
WAV_NAME = "audio.wav"
OPUS_NAME = "audio.opus"


def new_job_id() -> str:
    return str(uuid.uuid4())


def check_job_id(job_id: str) -> str:
    if not JOB_ID_RE.fullmatch(job_id):
        raise MM3Error(
            "E_JOB_NOT_FOUND",
            "That is not a valid job id.",
            "Job ids are UUIDs; list jobs with GET /api/jobs.",
            status_code=404,
        )
    return job_id


def job_dir(jobs_root: Path, job_id: str, *, create: bool = False) -> Path:
    """The folder of ``job_id`` under ``jobs_root``; the id is validated and the result must
    resolve inside the root (a symlinked job folder pointing elsewhere is refused)."""
    folder = jobs_root / check_job_id(job_id)
    if create:
        jobs_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        folder.mkdir(mode=0o700, exist_ok=True)
    if (folder.exists() or folder.is_symlink()) and not is_inside(jobs_root.resolve(), folder):
        raise MM3Error(
            "E_JOB_PATH",
            "The job folder resolves outside the app data folder.",
            "Remove the symbolic link from the jobs folder.",
            status_code=500,
        )
    return folder


def resolve_in_job(folder: Path, name: str | None) -> Path | None:
    """``folder / name`` if ``name`` is a plain file name that stays inside the folder."""
    if not name or "/" in name or "\\" in name or name in {".", ".."}:
        return None
    path = folder / name
    return path if is_inside(folder.resolve(), path) else None


def audio_files(folder: Path) -> list[Path]:
    """Every audio file MeetingMaster3 keeps in a job folder (upload, WAV, Opus, partials)."""
    if not folder.is_dir():
        return []
    found = [p for p in folder.glob("original.*") if p.is_file()]
    for name in (WAV_NAME, OPUS_NAME):
        if (folder / name).is_file():
            found.append(folder / name)
    found += [p for p in folder.glob(".*.part") if p.is_file()]
    return found


def remove_job_dir(jobs_root: Path, job_id: str) -> None:
    folder = job_dir(jobs_root, job_id)
    if folder.is_symlink():  # pragma: no cover - refused by job_dir already
        folder.unlink()
    elif folder.exists():
        shutil.rmtree(folder)
