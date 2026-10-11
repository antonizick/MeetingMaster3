"""Forward-only schema migrations, tracked in a ``schema_version`` table.

To change the schema, **append** a new :class:`Migration` to :data:`MIGRATIONS` with the next
version number. Never edit or reorder a migration that has shipped. A migration is either SQL
(run with ``executescript`` semantics, statement by statement) or a Python callable for data
moves. Each migration runs in its own transaction together with its ``schema_version`` row.
Later phases add their tables here (voiceprints in Phase 07, feedback in Phase 12).
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass

from meetingmaster3.errors import MM3Error


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str = ""
    func: Callable[[sqlite3.Connection], None] | None = None


_V1_JOBS = """
CREATE TABLE jobs (
    id               TEXT PRIMARY KEY,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    job_type         TEXT NOT NULL DEFAULT 'meeting',
    status           TEXT NOT NULL,
    title            TEXT NOT NULL DEFAULT '',
    meeting_date     TEXT,
    source_filename  TEXT NOT NULL DEFAULT '',
    audio_path       TEXT,
    duration_seconds REAL,
    settings_json    TEXT NOT NULL DEFAULT '{}',
    error_code       TEXT,
    error_message    TEXT,
    error_hint       TEXT,
    current_stage    TEXT,
    written_at       TEXT,
    audio_pinned     INTEGER NOT NULL DEFAULT 0,
    audio_expires_at TEXT,
    audio_pruned_at  TEXT
);
CREATE INDEX jobs_status ON jobs (status);
CREATE INDEX jobs_audio_expires_at ON jobs (audio_expires_at);

CREATE TABLE job_stages (
    job_id        TEXT NOT NULL REFERENCES jobs (id) ON DELETE CASCADE,
    stage         TEXT NOT NULL,
    position      INTEGER NOT NULL,
    status        TEXT NOT NULL,
    started_at    TEXT,
    finished_at   TEXT,
    artifact_path TEXT,
    attempt       INTEGER NOT NULL DEFAULT 0,
    detail_json   TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (job_id, stage)
);

CREATE TABLE recent_meetings (
    note_path       TEXT PRIMARY KEY,
    transcript_path TEXT,
    mm3_id          TEXT,
    title           TEXT NOT NULL DEFAULT '',
    date            TEXT,
    last_opened     TEXT NOT NULL
);
CREATE INDEX recent_meetings_last_opened ON recent_meetings (last_opened);
CREATE INDEX recent_meetings_mm3_id ON recent_meetings (mm3_id);
"""

_V2_VOICEPRINTS = """
CREATE TABLE voiceprints (
    person_id     TEXT PRIMARY KEY,
    display_name  TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    n_samples     INTEGER NOT NULL DEFAULT 0,
    total_seconds REAL NOT NULL DEFAULT 0
);

CREATE TABLE voiceprint_embeddings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id     TEXT NOT NULL REFERENCES voiceprints (person_id) ON DELETE CASCADE,
    embedding     BLOB NOT NULL,
    model_id      TEXT NOT NULL,
    source_job_id TEXT,
    seconds       REAL NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL
);
CREATE INDEX voiceprint_embeddings_model ON voiceprint_embeddings (model_id, person_id);
CREATE UNIQUE INDEX voiceprint_embeddings_source
    ON voiceprint_embeddings (person_id, model_id, source_job_id);
"""

MIGRATIONS: list[Migration] = [
    Migration(1, "jobs, job stages and recent meetings", sql=_V1_JOBS),
    Migration(2, "voiceprints (opt-in speaker recognition)", sql=_V2_VOICEPRINTS),
]


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def _split_sql(script: str) -> list[str]:
    statements, buf = [], ""
    for line in script.splitlines(keepends=True):
        buf += line
        if sqlite3.complete_statement(buf):
            statements.append(buf.strip())
            buf = ""
    if buf.strip():
        statements.append(buf.strip())
    return statements


def current_version(conn: sqlite3.Connection) -> int:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version ("
        " version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
    )
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    return int(row[0] or 0)


def migrate(conn: sqlite3.Connection, migrations: list[Migration] | None = None) -> int:
    """Apply every pending migration in order and return the resulting schema version.

    ``conn`` must be in autocommit mode (``isolation_level=None``)."""
    steps = sorted(MIGRATIONS if migrations is None else migrations, key=lambda m: m.version)
    versions = [m.version for m in steps]
    if len(set(versions)) != len(versions) or versions != list(range(1, len(versions) + 1)):
        raise ValueError(f"migration versions must be 1..N without gaps, got {versions}")
    version = current_version(conn)
    if version > len(steps):
        raise MM3Error(
            "E_DB_TOO_NEW",
            f"The database schema is version {version}, newer than this app supports "
            f"({len(steps)}).",
            "Upgrade MeetingMaster3, or restore a backup of mm3.db made by this version.",
            status_code=500,
        )
    for m in steps[version:]:
        conn.execute("BEGIN IMMEDIATE")
        try:
            for stmt in _split_sql(m.sql):
                conn.execute(stmt)
            if m.func is not None:
                m.func(conn)
            conn.execute(
                "INSERT INTO schema_version (version, name, applied_at) VALUES (?, ?, ?)",
                (m.version, m.name, _now()),
            )
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")
        version = m.version
    return version
