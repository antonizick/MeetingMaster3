from __future__ import annotations

import datetime as dt
import itertools
import sqlite3
from pathlib import Path

import pytest

from meetingmaster3.errors import MM3Error
from meetingmaster3.jobs.models import (
    TRANSITIONS,
    InvalidTransition,
    JobStatus,
    StageStatus,
    can_transition,
)
from meetingmaster3.storage.db import Database
from meetingmaster3.storage.migrations import MIGRATIONS, Migration, current_version, migrate
from meetingmaster3.storage.repositories import (
    JobNotFound,
    JobRepository,
    RecentMeetingsRepository,
    StageRepository,
)

JOB = "6f1c1c4e-2b7a-4c55-9d43-0a1b2c3d4e5f"


@pytest.fixture
def db(tmp_path: Path) -> Database:
    return Database.open(tmp_path / "mm3.db")


def test_database_uses_wal_and_private_mode(tmp_path: Path) -> None:
    db = Database.open(tmp_path / "sub" / "mm3.db")
    assert db.fetchone("PRAGMA journal_mode")[0] == "wal"  # type: ignore[index]
    assert db.fetchone("PRAGMA foreign_keys")[0] == 1  # type: ignore[index]
    assert ((tmp_path / "sub" / "mm3.db").stat().st_mode & 0o777) == 0o600


def test_migrations_are_idempotent_and_versioned(db: Database) -> None:
    assert db.migrate() == len(MIGRATIONS)
    rows = db.fetchall("SELECT version, name FROM schema_version")
    assert [r["version"] for r in rows] == list(range(1, len(MIGRATIONS) + 1))
    tables = {r[0] for r in db.fetchall("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"jobs", "job_stages", "recent_meetings", "schema_version"} <= tables


def test_later_migrations_apply_in_order_with_callables() -> None:
    conn = sqlite3.connect(":memory:", isolation_level=None)
    calls: list[int] = []
    steps = [
        *MIGRATIONS,
        Migration(len(MIGRATIONS) + 1, "extra", sql="CREATE TABLE extra_table (id TEXT);"),
        Migration(
            len(MIGRATIONS) + 2, "data move", func=lambda c: calls.append(current_version(c))
        ),
    ]
    assert migrate(conn, steps[: len(MIGRATIONS)]) == len(MIGRATIONS)
    assert migrate(conn, steps) == len(steps)
    assert calls == [len(MIGRATIONS) + 1]
    conn.execute("INSERT INTO extra_table VALUES ('x')")


def test_failed_migration_rolls_back() -> None:
    conn = sqlite3.connect(":memory:", isolation_level=None)
    bad = [*MIGRATIONS, Migration(len(MIGRATIONS) + 1, "bad", sql="CREATE TABLE t (a);\nNOPE;")]
    with pytest.raises(sqlite3.OperationalError):
        migrate(conn, bad)
    assert current_version(conn) == len(MIGRATIONS)
    assert conn.execute("SELECT name FROM sqlite_master WHERE name = 't'").fetchone() is None


def test_migration_list_must_be_contiguous_and_db_not_newer() -> None:
    conn = sqlite3.connect(":memory:", isolation_level=None)
    with pytest.raises(ValueError, match="without gaps"):
        migrate(conn, [Migration(2, "gap")])
    migrate(conn, [*MIGRATIONS, Migration(len(MIGRATIONS) + 1, "future")])
    with pytest.raises(MM3Error) as exc:
        migrate(conn)
    assert exc.value.code == "E_DB_TOO_NEW"


# -- job state machine (table-driven) ------------------------------------------------------

ALLOWED = {
    ("queued", "running"),
    ("queued", "cancelled"),
    ("running", "waiting_for_input"),
    ("running", "written"),
    ("running", "failed"),
    ("running", "cancelled"),
    ("running", "interrupted"),
    ("waiting_for_input", "queued"),
    ("waiting_for_input", "cancelled"),
    ("interrupted", "queued"),
    ("interrupted", "cancelled"),
    ("failed", "queued"),
    ("cancelled", "queued"),
}


@pytest.mark.parametrize(("old", "new"), list(itertools.product(list(JobStatus), list(JobStatus))))
def test_state_machine(db: Database, old: JobStatus, new: JobStatus) -> None:
    expected = (old.value, new.value) in ALLOWED
    assert can_transition(old, new) is expected
    jobs = JobRepository(db)
    jobs.create(JOB, stages=["a"], status=old)
    if expected:
        assert jobs.set_status(JOB, new).status is new
    else:
        with pytest.raises(InvalidTransition):
            jobs.set_status(JOB, new)
        assert jobs.get(JOB).status is old


def test_transition_table_covers_every_status() -> None:
    assert set(TRANSITIONS) == set(JobStatus)
    assert TRANSITIONS[JobStatus.WRITTEN] == frozenset()


def test_set_status_expected_guard(db: Database) -> None:
    jobs = JobRepository(db)
    jobs.create(JOB, stages=["a"])
    with pytest.raises(InvalidTransition):
        jobs.set_status(JOB, JobStatus.CANCELLED, expected={JobStatus.RUNNING})


# -- repositories ---------------------------------------------------------------------------


def test_job_repository_round_trip(db: Database) -> None:
    jobs, stages = JobRepository(db), StageRepository(db)
    job = jobs.create(
        JOB,
        stages=["ingest", "transcribe"],
        title="Sync",
        meeting_date=dt.date(2026, 10, 11),
        source_filename="a.m4a",
        audio_path="original.m4a",
        duration_seconds=12.5,
        settings={"diarize": True},
    )
    assert job.status is JobStatus.QUEUED and job.meeting_date == dt.date(2026, 10, 11)
    assert job.settings == {"diarize": True}
    assert [s.stage for s in stages.for_job(JOB)] == ["ingest", "transcribe"]
    assert all(s.status is StageStatus.PENDING for s in stages.for_job(JOB))

    when = dt.datetime(2026, 10, 11, 12, tzinfo=dt.UTC)
    job = jobs.update(JOB, audio_pinned=True, written_at=when, settings={"x": 1})
    assert job.audio_pinned and job.written_at == when and job.settings == {"x": 1}
    d = job.to_dict()
    assert d["audio"]["pinned"] is True and d["error"] is None
    with pytest.raises(ValueError, match="not updatable"):
        jobs.update(JOB, id="other")

    rec = stages.update(JOB, "ingest", status=StageStatus.COMPLETED, artifact_path="a.wav")
    assert rec.status is StageStatus.COMPLETED and rec.to_dict()["artifact"] == "a.wav"
    stages.reset_from(JOB, 0)
    assert stages.get(JOB, "ingest").artifact_path is None
    with pytest.raises(KeyError):
        stages.get(JOB, "nope")
    with pytest.raises(ValueError, match="not updatable"):
        stages.update(JOB, "ingest", position=3)

    assert [j.id for j in jobs.list_jobs({JobStatus.QUEUED})] == [JOB]
    assert jobs.list_jobs({JobStatus.WRITTEN}) == []
    jobs.delete(JOB)
    assert stages.for_job(JOB) == []  # cascade
    with pytest.raises(JobNotFound):
        jobs.get(JOB)
    with pytest.raises(JobNotFound):
        jobs.delete(JOB)
    with pytest.raises(JobNotFound):
        jobs.update(JOB, title="x")
    with pytest.raises(JobNotFound):
        jobs.set_status(JOB, JobStatus.RUNNING)


def test_recent_meetings_upsert(db: Database) -> None:
    repo = RecentMeetingsRepository(db)
    t1 = dt.datetime(2026, 10, 1, tzinfo=dt.UTC)
    t2 = dt.datetime(2026, 10, 2, tzinfo=dt.UTC)
    repo.touch("Meetings/a.md", transcript_path="Meetings/a.transcript.md", mm3_id="id-a",
               title="A", date=dt.date(2026, 10, 1), when=t1)  # fmt: skip
    repo.touch("Meetings/b.md", title="B", when=t2)
    assert [m.note_path for m in repo.recent()] == ["Meetings/b.md", "Meetings/a.md"]
    again = repo.touch("Meetings/a.md", when=t2 + dt.timedelta(days=1))
    assert again.title == "A" and again.mm3_id == "id-a" and again.date == dt.date(2026, 10, 1)
    assert repo.recent(limit=1)[0].note_path == "Meetings/a.md"
    assert again.to_dict()["transcript_path"] == "Meetings/a.transcript.md"
    repo.remove("Meetings/a.md")
    with pytest.raises(KeyError):
        repo.get("Meetings/a.md")
