"""The answer history in ``mm3.db`` (tables ``answers`` and ``answer_sources``, migration 5).

One row per saved answer: the question, when and how it was answered, where its note is in the
vault and which meetings it cites (``answer_sources``, so a meeting's review page can list the
answers that cite it). The vault note is the answer itself; this is the index over it.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from typing import Any

from meetingmaster3.storage.db import Database


@dataclass(frozen=True)
class SourceRef:
    mm3_id: str
    stem: str
    title: str
    date: str | None
    note_path: str | None
    relevance: str
    finding: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "mm3_id": self.mm3_id,
            "stem": self.stem,
            "title": self.title,
            "date": self.date,
            "note_path": self.note_path,
            "relevance": self.relevance,
            "finding": self.finding,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SourceRef:
        return cls(
            mm3_id=str(data.get("mm3_id") or ""),
            stem=str(data.get("stem") or ""),
            title=str(data.get("title") or ""),
            date=data.get("date"),
            note_path=data.get("note_path"),
            relevance=str(data.get("relevance") or "yes"),
            finding=str(data.get("finding") or ""),
        )


@dataclass(frozen=True)
class AnswerRecord:
    id: str
    question: str
    asked_at: dt.datetime
    backend: str
    model: str
    vault_path: str | None
    status: str
    duration_s: float | None
    input_tokens: int | None
    output_tokens: int | None
    relevant: int
    parent_id: str | None
    sources: tuple[SourceRef, ...] = field(default_factory=tuple)

    def findings(self) -> list[str]:
        return [f"{s.stem} ({s.date or 'no date'}): {s.finding}" for s in self.sources if s.finding]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "question": self.question,
            "asked_at": self.asked_at.isoformat(),
            "backend": self.backend,
            "model": self.model,
            "vault_path": self.vault_path,
            "status": self.status,
            "duration_s": self.duration_s,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "relevant": self.relevant,
            "parent_id": self.parent_id,
            "sources": [s.to_dict() for s in self.sources],
        }


class AnswerStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, record: AnswerRecord) -> AnswerRecord:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO answers (id, question, asked_at, backend, model, vault_path, status,"
                " duration_s, input_tokens, output_tokens, relevant, parent_id, sources_json)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.id,
                    record.question,
                    record.asked_at.isoformat(),
                    record.backend,
                    record.model,
                    record.vault_path,
                    record.status,
                    record.duration_s,
                    record.input_tokens,
                    record.output_tokens,
                    record.relevant,
                    record.parent_id,
                    json.dumps([s.to_dict() for s in record.sources], ensure_ascii=False),
                ),
            )
            conn.executemany(
                "INSERT OR IGNORE INTO answer_sources (answer_id, mm3_id) VALUES (?, ?)",
                [(record.id, s.mm3_id) for s in record.sources if s.mm3_id],
            )
        return record

    def get(self, answer_id: str) -> AnswerRecord | None:
        row = self.db.fetchone("SELECT * FROM answers WHERE id = ?", (answer_id,))
        return self._from_row(row) if row else None

    def recent(self, limit: int = 20, offset: int = 0) -> list[AnswerRecord]:
        rows = self.db.fetchall(
            "SELECT * FROM answers ORDER BY asked_at DESC, rowid DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        return [self._from_row(r) for r in rows]

    def count(self) -> int:
        row = self.db.fetchone("SELECT COUNT(*) AS n FROM answers")
        return int(row["n"]) if row else 0

    def citing(self, mm3_id: str, limit: int = 50) -> list[AnswerRecord]:
        """Answers that cite the meeting, newest first."""
        rows = self.db.fetchall(
            "SELECT a.* FROM answers a JOIN answer_sources s ON s.answer_id = a.id"
            " WHERE s.mm3_id = ? ORDER BY a.asked_at DESC LIMIT ?",
            (mm3_id, limit),
        )
        return [self._from_row(r) for r in rows]

    def set_path(self, answer_id: str, vault_path: str | None) -> None:
        self.db.execute("UPDATE answers SET vault_path = ? WHERE id = ?", (vault_path, answer_id))

    def delete(self, answer_id: str) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM answer_sources WHERE answer_id = ?", (answer_id,))
            conn.execute("DELETE FROM answers WHERE id = ?", (answer_id,))

    @staticmethod
    def _from_row(row: Any) -> AnswerRecord:
        try:
            sources = tuple(SourceRef.from_dict(d) for d in json.loads(row["sources_json"]))
        except (ValueError, TypeError, AttributeError):
            sources = ()
        return AnswerRecord(
            id=row["id"],
            question=row["question"],
            asked_at=dt.datetime.fromisoformat(row["asked_at"]),
            backend=row["backend"],
            model=row["model"],
            vault_path=row["vault_path"],
            status=row["status"],
            duration_s=row["duration_s"],
            input_tokens=row["input_tokens"],
            output_tokens=row["output_tokens"],
            relevant=int(row["relevant"] or 0),
            parent_id=row["parent_id"],
            sources=sources,
        )
