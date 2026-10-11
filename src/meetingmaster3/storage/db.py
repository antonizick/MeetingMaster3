"""SQLite connection handling (stdlib ``sqlite3``, WAL mode, one shared connection).

The app is single-user and writes are tiny (job and stage rows), so one connection guarded by a
re-entrant lock is enough. It is shared by the event loop and the stage worker threads.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from meetingmaster3.storage.migrations import migrate

Params = Sequence[Any] | dict[str, Any]


class Database:
    """A thread-safe wrapper around one SQLite connection."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path) if str(path) != ":memory:" else None
        if self.path is not None:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            str(path),
            check_same_thread=False,
            isolation_level=None,  # autocommit; explicit BEGIN in transaction()
            timeout=30,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA busy_timeout = 30000")
        # Deleted rows are overwritten with zeros, so deleting a voiceprint really erases it.
        self._conn.execute("PRAGMA secure_delete = ON")
        if self.path is not None:
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.execute("PRAGMA synchronous = NORMAL")
            self.path.chmod(0o600)

    @classmethod
    def open(cls, path: Path | str) -> Database:
        """Open (creating if needed) and migrate the database to the latest schema."""
        db = cls(path)
        db.migrate()
        return db

    def migrate(self) -> int:
        with self._lock:
            return migrate(self._conn)

    def execute(self, sql: str, params: Params = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, params)

    def fetchone(self, sql: str, params: Params = ()) -> sqlite3.Row | None:
        with self._lock:
            row: sqlite3.Row | None = self._conn.execute(sql, params).fetchone()
            return row

    def fetchall(self, sql: str, params: Params = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self._conn.execute(sql, params).fetchall())

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """``BEGIN IMMEDIATE`` … ``COMMIT`` (or ``ROLLBACK`` on error), holding the lock."""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")

    def checkpoint(self) -> None:
        """Copy the WAL into the database file and truncate it (after deleting sensitive rows,
        so no copy of them stays in ``mm3.db-wal``)."""
        with self._lock:
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def close(self) -> None:
        with self._lock:
            self._conn.close()
