"""Job and stage states, the job state machine, options and progress events."""

from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from meetingmaster3.errors import MM3Error


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_FOR_INPUT = "waiting_for_input"
    INTERRUPTED = "interrupted"  # the server stopped mid-job; resumable
    FAILED = "failed"  # resumable from the failed stage
    CANCELLED = "cancelled"  # resumable from the cancelled stage
    WRITTEN = "written"  # finished; terminal


class StageStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING = "waiting"  # human-in-the-loop pause
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


#: Allowed job transitions. Anything else is a bug and raises :class:`InvalidTransition`.
TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.QUEUED: frozenset({JobStatus.RUNNING, JobStatus.CANCELLED}),
    JobStatus.RUNNING: frozenset(
        {
            JobStatus.WAITING_FOR_INPUT,
            JobStatus.WRITTEN,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
            JobStatus.INTERRUPTED,
        }
    ),
    JobStatus.WAITING_FOR_INPUT: frozenset({JobStatus.QUEUED, JobStatus.CANCELLED}),
    JobStatus.INTERRUPTED: frozenset({JobStatus.QUEUED, JobStatus.CANCELLED}),
    JobStatus.FAILED: frozenset({JobStatus.QUEUED}),
    JobStatus.CANCELLED: frozenset({JobStatus.QUEUED}),
    JobStatus.WRITTEN: frozenset(),
}

#: Statuses from which ``resume`` is allowed.
RESUMABLE = frozenset({JobStatus.INTERRUPTED, JobStatus.FAILED, JobStatus.CANCELLED})
#: Statuses in which a job is active (holds or waits for a worker).
ACTIVE = frozenset({JobStatus.QUEUED, JobStatus.RUNNING})
#: Statuses after which the SSE stream closes.
FINAL = frozenset({JobStatus.WRITTEN, JobStatus.FAILED, JobStatus.CANCELLED})


class InvalidTransition(MM3Error):
    def __init__(self, job_id: str, old: JobStatus, new: JobStatus) -> None:
        super().__init__(
            "E_JOB_STATE",
            f"Job {job_id} cannot go from {old.value!r} to {new.value!r}.",
            "Refresh the job; its state changed in the meantime.",
            status_code=409,
        )
        self.old, self.new = old, new


def can_transition(old: JobStatus, new: JobStatus) -> bool:
    return new in TRANSITIONS[old]


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def iso(ts: dt.datetime | None) -> str | None:
    return ts.isoformat(timespec="seconds") if ts is not None else None


class JobOptions(BaseModel):
    """Options chosen at upload time (stored as ``jobs.settings_json``).

    Unknown keys are kept, so later phases can add options (template, backend, model, speaker
    hints, cloud consent) without a migration. ``resume`` overrides are merged into this.
    """

    model_config = ConfigDict(extra="allow")

    title: str = ""
    meeting_date: dt.date | None = None
    diarize: bool | None = None
    min_speakers: int | None = Field(default=None, ge=1, le=32)
    max_speakers: int | None = Field(default=None, ge=1, le=32)
    template: str | None = None
    backend: str | None = None
    model: str | None = None
    cloud_consent: bool = False


@dataclass(frozen=True)
class ProgressEvent:
    """One event on the progress bus and the SSE stream."""

    job_id: str
    stage: str | None
    status: str  # a StageStatus for stage events, a JobStatus for job events
    fraction: float | None = None
    message: str = ""
    eta_seconds: float | None = None
    kind: str = "stage"  # "stage" or "job"
    seq: int = 0
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
