"""Local feedback ratings on notes and sections (spec §3 step 9).

Ratings are stored in the local SQLite database only and are never sent anywhere: there is no
telemetry. ``export_rows`` gives the user their own data as JSON or CSV.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import sqlite3
from dataclasses import dataclass
from typing import Any, Literal

from meetingmaster3.errors import MM3Error
from meetingmaster3.storage.db import Database

RatingKind = Literal["thumbs", "stars"]
MAX_COMMENT = 2000
COLUMNS = (
    "id",
    "mm3_id",
    "template_id",
    "backend",
    "model",
    "section_id",
    "rating_kind",
    "value",
    "comment",
    "created_at",
)


@dataclass(frozen=True)
class Feedback:
    id: int
    mm3_id: str
    template_id: str | None
    backend: str | None
    model: str | None
    section_id: str | None
    rating_kind: RatingKind
    value: int
    comment: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in COLUMNS}

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Feedback:
        return cls(**{name: row[name] for name in COLUMNS})


def _invalid(message: str) -> MM3Error:
    return MM3Error("E_FEEDBACK_INVALID", message, "Rate with thumbs (-1 or 1) or 1-5 stars.", 422)


def validate_rating(kind: str, value: int) -> None:
    if kind == "thumbs" and value in (-1, 1):
        return
    if kind == "stars" and 1 <= value <= 5:
        return
    if kind not in ("thumbs", "stars"):
        raise _invalid(f"Unknown rating kind {kind!r}.")
    raise _invalid(f"{value} is not a valid {kind} rating.")


class FeedbackStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(
        self,
        mm3_id: str,
        *,
        rating_kind: str,
        value: int,
        comment: str = "",
        template_id: str | None = None,
        backend: str | None = None,
        model: str | None = None,
        section_id: str | None = None,
        now: dt.datetime | None = None,
    ) -> Feedback:
        """Record a rating. A new rating for the same note or section replaces the old one, so
        the table holds the latest opinion per (meeting, section)."""
        if not mm3_id.strip() or len(mm3_id) > 64:
            raise _invalid("A rating needs the meeting id.")
        validate_rating(rating_kind, value)
        comment = comment.strip()[:MAX_COMMENT]
        stamp = (now or dt.datetime.now(dt.UTC)).isoformat(timespec="seconds")
        with self.db.transaction() as conn:
            conn.execute(
                "DELETE FROM feedback WHERE mm3_id = ? AND rating_kind = ?"
                " AND COALESCE(section_id, '') = ?",
                (mm3_id, rating_kind, section_id or ""),
            )
            cur = conn.execute(
                "INSERT INTO feedback (mm3_id, template_id, backend, model, section_id,"
                " rating_kind, value, comment, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    mm3_id,
                    template_id,
                    backend,
                    model,
                    section_id or None,
                    rating_kind,
                    value,
                    comment,
                    stamp,
                ),
            )
            row_id = cur.lastrowid
        row = self.db.fetchone("SELECT * FROM feedback WHERE id = ?", (row_id,))
        if row is None:  # pragma: no cover - the row was just inserted
            raise RuntimeError("feedback row vanished")
        return Feedback.from_row(row)

    def for_meeting(self, mm3_id: str) -> list[Feedback]:
        rows = self.db.fetchall("SELECT * FROM feedback WHERE mm3_id = ? ORDER BY id", (mm3_id,))
        return [Feedback.from_row(r) for r in rows]

    def latest(self, mm3_id: str, section_id: str | None = None) -> Feedback | None:
        """The current rating for the note (``section_id=None``) or one section."""
        row = self.db.fetchone(
            "SELECT * FROM feedback WHERE mm3_id = ? AND COALESCE(section_id, '') = ?"
            " ORDER BY id DESC LIMIT 1",
            (mm3_id, section_id or ""),
        )
        return Feedback.from_row(row) if row else None

    def all(self) -> list[Feedback]:
        return [
            Feedback.from_row(r) for r in self.db.fetchall("SELECT * FROM feedback ORDER BY id")
        ]

    def delete(self, feedback_id: int) -> bool:
        return self.db.execute("DELETE FROM feedback WHERE id = ?", (feedback_id,)).rowcount > 0


def to_csv(rows: list[Feedback]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(COLUMNS)
    for row in rows:
        writer.writerow([_csv_safe(v) for v in (getattr(row, c) for c in COLUMNS)])
    return out.getvalue()


def _csv_safe(value: Any) -> Any:
    """Neutralise spreadsheet formulas in free text (CSV injection)."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value
