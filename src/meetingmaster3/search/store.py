"""The meeting index file ``<data>/search.db`` (Phase 15i, ADR-0049, ADR-0050).

It is derived data: everything in it can be rebuilt from the vault, so it has its own schema
version and is simply recreated when that changes, never migrated. It holds:

- ``documents``: one row per indexed vault file (a live note or a companion transcript) with its
  identity, metadata and the fingerprint (sha256, mtime, size) the incremental update compares;
- ``passages``: the chunks of each document, in order, with their section or time range;
- ``passages_fts``: an FTS5 word index over the passage text (external content, kept in step by
  triggers);
- ``vectors``: one float32 embedding per passage, tagged with the embedding model. Only one model
  is ever stored (``meta.embed_model``); a different model empties the table first.

The file is created 0600 in the 0700 data folder, with ``secure_delete`` on, so a deleted meeting
does not linger in free pages. One connection is shared by the event loop and worker threads,
guarded by a lock, like ``storage.db``.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
import threading
from array import array
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
SIDE_FILES = ("-wal", "-shm", "-journal")

SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE documents (
    id INTEGER PRIMARY KEY,
    mm3_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('note', 'transcript')),
    path TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    date TEXT,
    participants TEXT NOT NULL DEFAULT '[]',
    speakers TEXT NOT NULL DEFAULT '[]',
    people TEXT NOT NULL DEFAULT '',
    sha256 TEXT NOT NULL,
    mtime_ns INTEGER NOT NULL,
    size INTEGER NOT NULL,
    indexed_at TEXT NOT NULL
);
CREATE INDEX documents_mm3_id ON documents (mm3_id);
CREATE INDEX documents_date ON documents (date);
CREATE TABLE passages (
    id INTEGER PRIMARY KEY,
    doc_id INTEGER NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    ord INTEGER NOT NULL,
    text TEXT NOT NULL,
    text_hash TEXT NOT NULL,
    heading TEXT,
    section_id TEXT,
    start_s REAL,
    end_s REAL,
    speakers TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX passages_doc ON passages (doc_id);
CREATE INDEX passages_hash ON passages (text_hash);
CREATE VIRTUAL TABLE passages_fts USING fts5 (
    text, content='passages', content_rowid='id', tokenize='porter unicode61 remove_diacritics 2'
);
CREATE TRIGGER passages_ai AFTER INSERT ON passages BEGIN
    INSERT INTO passages_fts (rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER passages_ad AFTER DELETE ON passages BEGIN
    INSERT INTO passages_fts (passages_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;
CREATE TABLE vectors (
    passage_id INTEGER PRIMARY KEY REFERENCES passages (id) ON DELETE CASCADE,
    model TEXT NOT NULL,
    dims INTEGER NOT NULL,
    vec BLOB NOT NULL
);
"""


@dataclass(frozen=True)
class Passage:
    """One chunk of a document, ready to store."""

    text: str
    text_hash: str
    heading: str | None = None
    section_id: str | None = None
    start_s: float | None = None
    end_s: float | None = None
    speakers: tuple[str, ...] = ()


@dataclass(frozen=True)
class DocumentInfo:
    """What is known about a vault file before (or without) reading its passages."""

    mm3_id: str
    kind: str
    path: str
    """Relative to the vault root, with ``/``."""
    title: str
    date: str | None
    participants: tuple[str, ...]
    speakers: tuple[str, ...]
    sha256: str
    mtime_ns: int
    size: int


@dataclass(frozen=True)
class StoredDocument(DocumentInfo):
    id: int = 0
    indexed_at: str = ""


@dataclass
class Stats:
    documents: int = 0
    meetings: int = 0
    notes: int = 0
    transcripts: int = 0
    passages: int = 0
    vectors: int = 0
    size_bytes: int = 0
    meta: dict[str, str] = field(default_factory=dict)


def _people(info: DocumentInfo) -> str:
    """The lower-cased names a person filter matches against, one per line."""
    return "\n".join(sorted({p.casefold() for p in (*info.participants, *info.speakers) if p}))


def pack(vec: Sequence[float]) -> bytes:
    return array("f", vec).tobytes()


def unpack(blob: bytes) -> array[float]:
    out = array("f")
    out.frombytes(blob)
    return out


class SearchStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path) if str(path) != ":memory:" else None
        self._lock = threading.RLock()
        self.generation = 0
        """Bumped by every write, so readers can tell when a cache is stale."""
        self._conn = self._connect(path)

    # -- opening ---------------------------------------------------------------------------

    def _connect(self, path: Path | str) -> sqlite3.Connection:
        if self.path is not None:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if not self.path.exists():
                self.path.touch(mode=0o600)
            self.path.chmod(0o600)
        conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA secure_delete = ON")
        if self.path is not None:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version != SCHEMA_VERSION:
            self._create(conn, fresh=version == 0)
        return conn

    @staticmethod
    def _create(conn: sqlite3.Connection, *, fresh: bool) -> None:
        """Create the schema; an index of another schema version is dropped and rebuilt."""
        drops = ""
        if not fresh:
            conn.execute("PRAGMA foreign_keys = OFF")
            names = [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' "
                    "AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'passages_fts_%'"
                ).fetchall()
            ]
            drops = "".join(f'DROP TABLE IF EXISTS "{n}";' for n in names)
        # One script, so the schema is created whole or not at all.
        try:
            conn.executescript(
                f"BEGIN IMMEDIATE;{drops}{SCHEMA}PRAGMA user_version = {SCHEMA_VERSION};COMMIT;"
            )
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.execute("PRAGMA foreign_keys = ON")

    @classmethod
    def open(cls, path: Path | str) -> SearchStore:
        return cls(path)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")
            self.generation += 1

    def fetchall(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self._conn.execute(sql, params).fetchall())

    def fetchone(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
        with self._lock:
            row: sqlite3.Row | None = self._conn.execute(sql, params).fetchone()
            return row

    # -- meta ------------------------------------------------------------------------------

    def get_meta(self, key: str) -> str | None:
        row = self.fetchone("SELECT value FROM meta WHERE key = ?", (key,))
        return None if row is None else str(row["value"])

    def set_meta(self, **values: str | None) -> None:
        with self.transaction() as conn:
            for key, value in values.items():
                if value is None:
                    conn.execute("DELETE FROM meta WHERE key = ?", (key,))
                else:
                    conn.execute(
                        "INSERT INTO meta (key, value) VALUES (?, ?) "
                        "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                        (key, value),
                    )

    def all_meta(self) -> dict[str, str]:
        return {r["key"]: r["value"] for r in self.fetchall("SELECT key, value FROM meta")}

    # -- documents -------------------------------------------------------------------------

    @staticmethod
    def _document(row: sqlite3.Row) -> StoredDocument:
        return StoredDocument(
            id=int(row["id"]),
            mm3_id=row["mm3_id"],
            kind=row["kind"],
            path=row["path"],
            title=row["title"],
            date=row["date"],
            participants=tuple(json.loads(row["participants"])),
            speakers=tuple(json.loads(row["speakers"])),
            sha256=row["sha256"],
            mtime_ns=int(row["mtime_ns"]),
            size=int(row["size"]),
            indexed_at=row["indexed_at"],
        )

    def documents(self) -> list[StoredDocument]:
        return [self._document(r) for r in self.fetchall("SELECT * FROM documents ORDER BY id")]

    def documents_for(self, mm3_ids: Sequence[str]) -> list[StoredDocument]:
        if not mm3_ids:
            return []
        marks = ",".join("?" * len(mm3_ids))
        rows = self.fetchall(
            f"SELECT * FROM documents WHERE mm3_id IN ({marks}) ORDER BY id",  # noqa: S608
            list(mm3_ids),
        )
        return [self._document(r) for r in rows]

    def put_document(self, info: DocumentInfo, passages: Sequence[Passage], now: str) -> int:
        """Replace the document at ``info.path`` (and its passages) in one transaction. Vectors
        of passages whose text did not change are kept (matched by ``text_hash``)."""
        with self.transaction() as conn:
            old = conn.execute("SELECT id FROM documents WHERE path = ?", (info.path,)).fetchone()
            kept: dict[str, tuple[str, int, bytes]] = {}
            if old is not None:
                for r in conn.execute(
                    "SELECT p.text_hash, v.model, v.dims, v.vec FROM passages p "
                    "JOIN vectors v ON v.passage_id = p.id WHERE p.doc_id = ?",
                    (old["id"],),
                ):
                    kept[r["text_hash"]] = (r["model"], r["dims"], r["vec"])
                conn.execute("DELETE FROM documents WHERE id = ?", (old["id"],))
            cur = conn.execute(
                "INSERT INTO documents (mm3_id, kind, path, title, date, participants, speakers, "
                "people, sha256, mtime_ns, size, indexed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    info.mm3_id,
                    info.kind,
                    info.path,
                    info.title,
                    info.date,
                    json.dumps(list(info.participants)),
                    json.dumps(list(info.speakers)),
                    _people(info),
                    info.sha256,
                    info.mtime_ns,
                    info.size,
                    now,
                ),
            )
            doc_id = int(cur.lastrowid or 0)
            for order, p in enumerate(passages):
                pcur = conn.execute(
                    "INSERT INTO passages (doc_id, ord, text, text_hash, heading, section_id, "
                    "start_s, end_s, speakers) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        doc_id,
                        order,
                        p.text,
                        p.text_hash,
                        p.heading,
                        p.section_id,
                        p.start_s,
                        p.end_s,
                        json.dumps(list(p.speakers)),
                    ),
                )
                if p.text_hash in kept:
                    model, dims, vec = kept[p.text_hash]
                    conn.execute(
                        "INSERT INTO vectors (passage_id, model, dims, vec) VALUES (?, ?, ?, ?)",
                        (pcur.lastrowid, model, dims, vec),
                    )
            return doc_id

    def move_document(self, doc_id: int, path: str, mtime_ns: int, now: str) -> None:
        """Point a document at its new path (a file moved or renamed without changing)."""
        with self.transaction() as conn:
            conn.execute(
                "UPDATE documents SET path = ?, mtime_ns = ?, indexed_at = ? WHERE id = ?",
                (path, mtime_ns, now, doc_id),
            )

    def touch_document(self, doc_id: int, mtime_ns: int) -> None:
        """Record a new mtime for a file whose content did not change."""
        with self.transaction() as conn:
            conn.execute("UPDATE documents SET mtime_ns = ? WHERE id = ?", (mtime_ns, doc_id))

    def delete_documents(self, doc_ids: Sequence[int]) -> None:
        if not doc_ids:
            return
        with self.transaction() as conn:
            conn.executemany("DELETE FROM documents WHERE id = ?", [(i,) for i in doc_ids])

    # -- vectors ---------------------------------------------------------------------------

    def drop_vectors_not_of(self, model: str) -> int:
        """Delete every vector of another embedding model (never mix vectors)."""
        with self.transaction() as conn:
            cur = conn.execute("DELETE FROM vectors WHERE model != ?", (model,))
            return cur.rowcount

    def passages_without_vectors(self, limit: int) -> list[tuple[int, str]]:
        rows = self.fetchall(
            "SELECT p.id, p.text FROM passages p LEFT JOIN vectors v ON v.passage_id = p.id "
            "WHERE v.passage_id IS NULL ORDER BY p.id LIMIT ?",
            (limit,),
        )
        return [(int(r["id"]), str(r["text"])) for r in rows]

    def count_without_vectors(self) -> int:
        row = self.fetchone(
            "SELECT COUNT(*) AS n FROM passages p LEFT JOIN vectors v ON v.passage_id = p.id "
            "WHERE v.passage_id IS NULL"
        )
        return int(row["n"]) if row else 0

    def put_vectors(self, model: str, items: Sequence[tuple[int, Sequence[float]]]) -> None:
        with self.transaction() as conn:
            for passage_id, vec in items:
                # A passage deleted meanwhile (its note changed) is skipped by the join.
                conn.execute(
                    "INSERT OR REPLACE INTO vectors (passage_id, model, dims, vec) "
                    "SELECT id, ?, ?, ? FROM passages WHERE id = ?",
                    (model, len(vec), pack(vec), passage_id),
                )

    def vectors(self, model: str) -> list[tuple[int, int, bytes]]:
        """``(passage_id, doc_id, blob)`` for every vector of ``model``."""
        rows = self.fetchall(
            "SELECT v.passage_id, p.doc_id, v.vec FROM vectors v "
            "JOIN passages p ON p.id = v.passage_id WHERE v.model = ?",
            (model,),
        )
        return [(int(r["passage_id"]), int(r["doc_id"]), bytes(r["vec"])) for r in rows]

    # -- whole index -----------------------------------------------------------------------

    def clear(self) -> None:
        with self.transaction() as conn:
            conn.execute("DELETE FROM documents")
            conn.execute("DELETE FROM meta")
            conn.execute("INSERT INTO passages_fts (passages_fts) VALUES ('rebuild')")

    def stats(self) -> Stats:
        row = self.fetchone(
            "SELECT (SELECT COUNT(*) FROM documents) AS documents, "
            "(SELECT COUNT(DISTINCT mm3_id) FROM documents) AS meetings, "
            "(SELECT COUNT(*) FROM documents WHERE kind = 'note') AS notes, "
            "(SELECT COUNT(*) FROM documents WHERE kind = 'transcript') AS transcripts, "
            "(SELECT COUNT(*) FROM passages) AS passages, "
            "(SELECT COUNT(*) FROM vectors) AS vectors"
        )
        assert row is not None  # noqa: S101 - an aggregate query always returns a row
        size = 0
        if self.path is not None:
            for suffix in ("", *SIDE_FILES):
                with contextlib.suppress(OSError):
                    size += Path(str(self.path) + suffix).stat().st_size
        return Stats(
            documents=row["documents"],
            meetings=row["meetings"],
            notes=row["notes"],
            transcripts=row["transcripts"],
            passages=row["passages"],
            vectors=row["vectors"],
            size_bytes=size,
            meta=self.all_meta(),
        )


def delete_index_files(path: Path) -> list[Path]:
    """Remove ``search.db`` and its WAL/SHM side files. Returns what was removed."""
    removed = []
    for suffix in ("", *SIDE_FILES):
        target = Path(str(path) + suffix)
        with contextlib.suppress(FileNotFoundError):
            target.unlink()
            removed.append(target)
    return removed
