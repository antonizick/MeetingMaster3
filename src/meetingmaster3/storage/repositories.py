"""Typed repositories over the SQLite tables (jobs, job stages, recent meetings)."""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from meetingmaster3.errors import MM3Error
from meetingmaster3.jobs.models import (
    InvalidTransition,
    JobStatus,
    StageStatus,
    can_transition,
    iso,
    utcnow,
)
from meetingmaster3.storage.db import Database


def _parse_ts(value: str | None) -> dt.datetime | None:
    return dt.datetime.fromisoformat(value) if value else None


def _parse_date(value: str | None) -> dt.date | None:
    return dt.date.fromisoformat(value) if value else None


@dataclass(frozen=True)
class JobRecord:
    id: str
    created_at: dt.datetime
    updated_at: dt.datetime
    job_type: str
    status: JobStatus
    title: str
    meeting_date: dt.date | None
    source_filename: str
    audio_path: str | None
    duration_seconds: float | None
    settings: dict[str, Any]
    error_code: str | None
    error_message: str | None
    error_hint: str | None
    current_stage: str | None
    written_at: dt.datetime | None
    audio_pinned: bool
    audio_expires_at: dt.datetime | None
    audio_pruned_at: dt.datetime | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> JobRecord:
        return cls(
            id=row["id"],
            created_at=dt.datetime.fromisoformat(row["created_at"]),
            updated_at=dt.datetime.fromisoformat(row["updated_at"]),
            job_type=row["job_type"],
            status=JobStatus(row["status"]),
            title=row["title"],
            meeting_date=_parse_date(row["meeting_date"]),
            source_filename=row["source_filename"],
            audio_path=row["audio_path"],
            duration_seconds=row["duration_seconds"],
            settings=json.loads(row["settings_json"]),
            error_code=row["error_code"],
            error_message=row["error_message"],
            error_hint=row["error_hint"],
            current_stage=row["current_stage"],
            written_at=_parse_ts(row["written_at"]),
            audio_pinned=bool(row["audio_pinned"]),
            audio_expires_at=_parse_ts(row["audio_expires_at"]),
            audio_pruned_at=_parse_ts(row["audio_pruned_at"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "created_at": iso(self.created_at),
            "updated_at": iso(self.updated_at),
            "job_type": self.job_type,
            "status": self.status.value,
            "title": self.title,
            "meeting_date": self.meeting_date.isoformat() if self.meeting_date else None,
            "source_filename": self.source_filename,
            "duration_seconds": self.duration_seconds,
            "options": self.settings,
            "error": (
                {"code": self.error_code, "message": self.error_message, "hint": self.error_hint}
                if self.error_code
                else None
            ),
            "current_stage": self.current_stage,
            "written_at": iso(self.written_at),
            "audio": {
                "available": self.audio_path is not None,
                "pinned": self.audio_pinned,
                "expires_at": iso(self.audio_expires_at),
                "pruned_at": iso(self.audio_pruned_at),
            },
        }


@dataclass(frozen=True)
class StageRecord:
    job_id: str
    stage: str
    position: int
    status: StageStatus
    started_at: dt.datetime | None
    finished_at: dt.datetime | None
    artifact_path: str | None
    attempt: int
    detail: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> StageRecord:
        return cls(
            job_id=row["job_id"],
            stage=row["stage"],
            position=row["position"],
            status=StageStatus(row["status"]),
            started_at=_parse_ts(row["started_at"]),
            finished_at=_parse_ts(row["finished_at"]),
            artifact_path=row["artifact_path"],
            attempt=row["attempt"],
            detail=json.loads(row["detail_json"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "position": self.position,
            "status": self.status.value,
            "started_at": iso(self.started_at),
            "finished_at": iso(self.finished_at),
            "artifact": self.artifact_path,
            "attempt": self.attempt,
            "detail": self.detail,
        }


class JobNotFound(MM3Error):
    def __init__(self, job_id: str) -> None:
        super().__init__(
            "E_JOB_NOT_FOUND",
            f"No job with id {job_id!r}.",
            "Check the id, or list jobs with GET /api/jobs.",
            status_code=404,
        )


_UPDATABLE = frozenset(
    {
        "title",
        "meeting_date",
        "audio_path",
        "duration_seconds",
        "settings_json",
        "error_code",
        "error_message",
        "error_hint",
        "current_stage",
        "written_at",
        "audio_pinned",
        "audio_expires_at",
        "audio_pruned_at",
    }
)


class JobRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create(
        self,
        job_id: str,
        *,
        stages: list[str],
        title: str = "",
        meeting_date: dt.date | None = None,
        source_filename: str = "",
        audio_path: str | None = None,
        duration_seconds: float | None = None,
        settings: dict[str, Any] | None = None,
        job_type: str = "meeting",
        status: JobStatus = JobStatus.QUEUED,
    ) -> JobRecord:
        now = iso(utcnow())
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO jobs (id, created_at, updated_at, job_type, status, title,"
                " meeting_date, source_filename, audio_path, duration_seconds, settings_json)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    job_id,
                    now,
                    now,
                    job_type,
                    status.value,
                    title,
                    meeting_date.isoformat() if meeting_date else None,
                    source_filename,
                    audio_path,
                    duration_seconds,
                    json.dumps(settings or {}, default=str),
                ),
            )
            conn.executemany(
                "INSERT INTO job_stages (job_id, stage, position, status) VALUES (?, ?, ?, ?)",
                [(job_id, s, i, StageStatus.PENDING.value) for i, s in enumerate(stages)],
            )
        return self.get(job_id)

    def find(self, job_id: str) -> JobRecord | None:
        row = self.db.fetchone("SELECT * FROM jobs WHERE id = ?", (job_id,))
        return JobRecord.from_row(row) if row else None

    def get(self, job_id: str) -> JobRecord:
        job = self.find(job_id)
        if job is None:
            raise JobNotFound(job_id)
        return job

    def list_jobs(
        self, statuses: set[JobStatus] | None = None, limit: int = 200, offset: int = 0
    ) -> list[JobRecord]:
        sql = "SELECT * FROM jobs"
        params: list[Any] = []
        if statuses:
            sql += f" WHERE status IN ({','.join('?' * len(statuses))})"
            params.extend(s.value for s in statuses)
        sql += " ORDER BY created_at DESC, id LIMIT ? OFFSET ?"
        params += [limit, offset]
        return [JobRecord.from_row(r) for r in self.db.fetchall(sql, params)]

    def set_status(
        self,
        job_id: str,
        new: JobStatus,
        *,
        expected: set[JobStatus] | None = None,
        **fields: Any,
    ) -> JobRecord:
        """Move a job to ``new``, enforcing :data:`~meetingmaster3.jobs.models.TRANSITIONS`
        (and ``expected``, if given) atomically; ``fields`` are updated in the same statement."""
        with self.db.transaction() as conn:
            row = conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                raise JobNotFound(job_id)
            old = JobStatus(row["status"])
            if (expected is not None and old not in expected) or not can_transition(old, new):
                raise InvalidTransition(job_id, old, new)
            self._update(conn, job_id, {"status": new.value, **fields})
        return self.get(job_id)

    def update(self, job_id: str, **fields: Any) -> JobRecord:
        with self.db.transaction() as conn:
            self._update(conn, job_id, fields)
        return self.get(job_id)

    @staticmethod
    def _update(conn: sqlite3.Connection, job_id: str, fields: dict[str, Any]) -> None:
        fields = dict(fields)
        if "settings" in fields:
            fields["settings_json"] = json.dumps(fields.pop("settings"), default=str)
        unknown = set(fields) - _UPDATABLE - {"status"}
        if unknown:
            raise ValueError(f"not updatable: {sorted(unknown)}")
        for key, value in list(fields.items()):
            if isinstance(value, dt.datetime):
                fields[key] = iso(value)
            elif isinstance(value, dt.date):
                fields[key] = value.isoformat()
            elif isinstance(value, bool):
                fields[key] = int(value)
        fields["updated_at"] = iso(utcnow())
        assignments = ", ".join(f"{k} = ?" for k in fields)
        cur = conn.execute(
            f"UPDATE jobs SET {assignments} WHERE id = ?",  # noqa: S608 - keys are allowlisted
            [*fields.values(), job_id],
        )
        if cur.rowcount == 0:
            raise JobNotFound(job_id)

    def delete(self, job_id: str) -> None:
        cur = self.db.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        if cur.rowcount == 0:
            raise JobNotFound(job_id)


class StageRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def for_job(self, job_id: str) -> list[StageRecord]:
        rows = self.db.fetchall(
            "SELECT * FROM job_stages WHERE job_id = ? ORDER BY position", (job_id,)
        )
        return [StageRecord.from_row(r) for r in rows]

    def get(self, job_id: str, stage: str) -> StageRecord:
        row = self.db.fetchone(
            "SELECT * FROM job_stages WHERE job_id = ? AND stage = ?", (job_id, stage)
        )
        if row is None:
            raise KeyError(f"{job_id}/{stage}")
        return StageRecord.from_row(row)

    def update(self, job_id: str, stage: str, **fields: Any) -> StageRecord:
        fields = dict(fields)
        if "detail" in fields:
            fields["detail_json"] = json.dumps(fields.pop("detail"), default=str)
        for key, value in list(fields.items()):
            if isinstance(value, StageStatus):
                fields[key] = value.value
            elif isinstance(value, dt.datetime):
                fields[key] = iso(value)
        allowed = {"status", "started_at", "finished_at", "artifact_path", "attempt", "detail_json"}
        if set(fields) - allowed:
            raise ValueError(f"not updatable: {sorted(set(fields) - allowed)}")
        assignments = ", ".join(f"{k} = ?" for k in fields)
        self.db.execute(
            f"UPDATE job_stages SET {assignments} WHERE job_id = ? AND stage = ?",  # noqa: S608
            [*fields.values(), job_id, stage],
        )
        return self.get(job_id, stage)

    def reset_from(self, job_id: str, position: int) -> None:
        """Mark every stage at or after ``position`` pending again (their artifacts are stale)."""
        self.db.execute(
            "UPDATE job_stages SET status = ?, started_at = NULL, finished_at = NULL,"
            " artifact_path = NULL WHERE job_id = ? AND position >= ? AND status != ?",
            (StageStatus.PENDING.value, job_id, position, StageStatus.PENDING.value),
        )

    def mark_running_interrupted(self) -> int:
        cur = self.db.execute(
            "UPDATE job_stages SET status = ? WHERE status = ?",
            (StageStatus.INTERRUPTED.value, StageStatus.RUNNING.value),
        )
        return cur.rowcount


@dataclass(frozen=True)
class RecentMeeting:
    note_path: str
    transcript_path: str | None
    mm3_id: str | None
    title: str
    date: dt.date | None
    last_opened: dt.datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "note_path": self.note_path,
            "transcript_path": self.transcript_path,
            "mm3_id": self.mm3_id,
            "title": self.title,
            "date": self.date.isoformat() if self.date else None,
            "last_opened": iso(self.last_opened),
        }


class RecentMeetingsRepository:
    """Notes written or re-opened recently (Phase 09 writes, Phases 10 and 11 list and re-open)."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def touch(
        self,
        note_path: str,
        *,
        transcript_path: str | None = None,
        mm3_id: str | None = None,
        title: str = "",
        date: dt.date | None = None,
        when: dt.datetime | None = None,
    ) -> RecentMeeting:
        self.db.execute(
            "INSERT INTO recent_meetings (note_path, transcript_path, mm3_id, title, date,"
            " last_opened) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (note_path) DO UPDATE SET"
            " transcript_path = COALESCE(excluded.transcript_path, transcript_path),"
            " mm3_id = COALESCE(excluded.mm3_id, mm3_id),"
            " title = CASE WHEN excluded.title != '' THEN excluded.title ELSE title END,"
            " date = COALESCE(excluded.date, date), last_opened = excluded.last_opened",
            (
                note_path,
                transcript_path,
                mm3_id,
                title,
                date.isoformat() if date else None,
                iso(when or utcnow()),
            ),
        )
        return self.get(note_path)

    def get(self, note_path: str) -> RecentMeeting:
        row = self.db.fetchone("SELECT * FROM recent_meetings WHERE note_path = ?", (note_path,))
        if row is None:
            raise KeyError(note_path)
        return self._from_row(row)

    def recent(self, limit: int = 50) -> list[RecentMeeting]:
        rows = self.db.fetchall(
            "SELECT * FROM recent_meetings ORDER BY last_opened DESC LIMIT ?", (limit,)
        )
        return [self._from_row(r) for r in rows]

    def remove(self, note_path: str) -> None:
        self.db.execute("DELETE FROM recent_meetings WHERE note_path = ?", (note_path,))

    @staticmethod
    def _from_row(row: sqlite3.Row) -> RecentMeeting:
        return RecentMeeting(
            note_path=row["note_path"],
            transcript_path=row["transcript_path"],
            mm3_id=row["mm3_id"],
            title=row["title"],
            date=_parse_date(row["date"]),
            last_opened=dt.datetime.fromisoformat(row["last_opened"]),
        )
