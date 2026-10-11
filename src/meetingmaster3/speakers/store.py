"""The local voiceprint store (opt-in biometric data, spec S7).

Two tables in ``mm3.db`` (migration 2): ``voiceprints`` (one row per person: name, counts, times)
and ``voiceprint_embeddings`` (float32 vectors, each tagged with the embedding ``model_id`` and the
job it came from). Nothing is ever written unless ``privacy.voiceprints_enabled`` is true; reading
for suggestions also stops when it is false. Listing and deleting always work, so a user can
remove what was stored after turning the feature off. The vectors never leave this module: the
API and CLI see names, counts and dates only. Deletes are physical (``secure_delete``) and are
followed by a WAL checkpoint, so no copy stays in ``mm3.db-wal``.
"""

from __future__ import annotations

import logging
import secrets
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from meetingmaster3.domain.transcript import clean_name
from meetingmaster3.errors import MM3Error
from meetingmaster3.jobs.models import iso, utcnow
from meetingmaster3.speakers.match import KnownPerson
from meetingmaster3.speakers.vectors import Vector, from_blob, normalize, to_blob
from meetingmaster3.storage.db import Database

log = logging.getLogger(__name__)

MAX_EMBEDDINGS_PER_PERSON = 20
MAX_NAME_LENGTH = 200


@dataclass(frozen=True)
class Person:
    person_id: str
    display_name: str
    created_at: str
    updated_at: str
    n_samples: int
    total_seconds: float
    models: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Public view: never the vectors."""
        return {
            "person_id": self.person_id,
            "name": self.display_name,
            "created_at": self.created_at,
            "last_seen": self.updated_at,
            "samples": self.n_samples,
            "total_seconds": round(self.total_seconds, 1),
            "models": list(self.models),
        }


def disabled_error() -> MM3Error:
    return MM3Error(
        "E_VOICEPRINTS_DISABLED",
        "Voice recognition is turned off, so no voiceprint was saved.",
        "Turn on privacy.voiceprints_enabled in Settings to let MeetingMaster3 remember voices.",
        status_code=409,
    )


def not_found(person_id: str) -> MM3Error:
    return MM3Error(
        "E_PERSON_NOT_FOUND",
        f"No stored voice with id {person_id!r}.",
        "List the stored voices with GET /api/voiceprints or `mm3 voiceprints list`.",
        status_code=404,
    )


def check_person_id(person_id: str) -> str:
    try:
        return uuid.UUID(person_id).hex
    except (ValueError, AttributeError, TypeError) as exc:
        raise not_found(str(person_id)[:64]) from exc


class VoiceprintStore:
    def __init__(
        self,
        db: Database,
        *,
        enabled: bool,
        max_embeddings: int = MAX_EMBEDDINGS_PER_PERSON,
    ) -> None:
        self.db = db
        self.enabled = enabled
        self.max_embeddings = max_embeddings

    # -- reading -----------------------------------------------------------------------------

    def _person(self, row: Any) -> Person:
        models = self.db.fetchall(
            "SELECT DISTINCT model_id FROM voiceprint_embeddings WHERE person_id = ? "
            "ORDER BY model_id",
            (row["person_id"],),
        )
        return Person(
            person_id=row["person_id"],
            display_name=row["display_name"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            n_samples=int(row["n_samples"]),
            total_seconds=float(row["total_seconds"]),
            models=tuple(r["model_id"] for r in models),
        )

    def list_people(self) -> list[Person]:
        rows = self.db.fetchall(
            "SELECT * FROM voiceprints ORDER BY display_name COLLATE NOCASE, created_at"
        )
        return [self._person(r) for r in rows]

    def find(self, person_id: str) -> Person | None:
        try:
            pid = check_person_id(person_id)
        except MM3Error:
            return None
        row = self.db.fetchone("SELECT * FROM voiceprints WHERE person_id = ?", (pid,))
        return self._person(row) if row is not None else None

    def get(self, person_id: str) -> Person:
        person = self.find(person_id)
        if person is None:
            raise not_found(person_id)
        return person

    def find_by_name(self, name: str) -> list[Person]:
        wanted = clean_name(name).casefold()
        return [p for p in self.list_people() if p.display_name.casefold() == wanted]

    def known_people(self, model_id: str) -> list[KnownPerson]:
        """Everyone with embeddings from ``model_id`` (others are never compared). Empty while
        the feature is disabled."""
        if not self.enabled:
            return []
        rows = self.db.fetchall(
            "SELECT v.person_id, v.display_name, e.embedding FROM voiceprints v "
            "JOIN voiceprint_embeddings e ON e.person_id = v.person_id "
            "WHERE e.model_id = ? ORDER BY v.person_id, e.id",
            (model_id,),
        )
        people: dict[str, tuple[str, list[Vector]]] = {}
        for r in rows:
            people.setdefault(r["person_id"], (r["display_name"], []))[1].append(
                from_blob(r["embedding"])
            )
        return [KnownPerson(pid, name, vecs) for pid, (name, vecs) in people.items()]

    def count_rows(self) -> dict[str, int]:
        people = self.db.fetchone("SELECT COUNT(*) FROM voiceprints")
        vectors = self.db.fetchone("SELECT COUNT(*) FROM voiceprint_embeddings")
        return {
            "voiceprints": int(people[0]) if people else 0,
            "voiceprint_embeddings": int(vectors[0]) if vectors else 0,
        }

    # -- writing (only when enabled) -----------------------------------------------------------

    def _require_enabled(self) -> None:
        if not self.enabled:
            raise disabled_error()

    def create_person(self, name: str) -> Person:
        self._require_enabled()
        display = clean_name(name)
        if not display or len(display) > MAX_NAME_LENGTH:
            raise MM3Error(
                "E_INPUT_INVALID",
                f"A name needs 1 to {MAX_NAME_LENGTH} characters.",
                "Type the person's name.",
                status_code=422,
            )
        pid = uuid.uuid4().hex
        now = iso(utcnow())
        self.db.execute(
            "INSERT INTO voiceprints (person_id, display_name, created_at, updated_at) "
            "VALUES (?, ?, ?, ?)",
            (pid, display, now, now),
        )
        return self.get(pid)

    def rename(self, person_id: str, name: str) -> Person:
        display = clean_name(name)
        if not display or len(display) > MAX_NAME_LENGTH:
            raise MM3Error(
                "E_INPUT_INVALID",
                f"A name needs 1 to {MAX_NAME_LENGTH} characters.",
                "Type the person's name.",
                status_code=422,
            )
        person = self.get(person_id)
        self.db.execute(
            "UPDATE voiceprints SET display_name = ? WHERE person_id = ?",
            (display, person.person_id),
        )
        return self.get(person.person_id)

    def add_embedding(
        self,
        person_id: str,
        embedding: Sequence[float],
        *,
        model_id: str,
        seconds: float,
        source_job_id: str | None,
    ) -> Person:
        """Store one embedding (replacing an earlier one from the same job and model, so a
        re-run never double-counts) and keep the newest ``max_embeddings`` per model."""
        self._require_enabled()
        person = self.get(person_id)
        blob = to_blob(normalize(embedding))
        now = iso(utcnow())
        with self.db.transaction() as conn:
            if source_job_id is not None:
                conn.execute(
                    "DELETE FROM voiceprint_embeddings "
                    "WHERE person_id = ? AND model_id = ? AND source_job_id = ?",
                    (person.person_id, model_id, source_job_id),
                )
            conn.execute(
                "INSERT INTO voiceprint_embeddings "
                "(person_id, embedding, model_id, source_job_id, seconds, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (person.person_id, blob, model_id, source_job_id, float(seconds), now),
            )
            conn.execute(
                "DELETE FROM voiceprint_embeddings WHERE person_id = ? AND model_id = ? AND id "
                "NOT IN (SELECT id FROM voiceprint_embeddings WHERE person_id = ? AND "
                "model_id = ? ORDER BY id DESC LIMIT ?)",
                (person.person_id, model_id, person.person_id, model_id, self.max_embeddings),
            )
            conn.execute(
                "UPDATE voiceprints SET updated_at = ?, "
                "n_samples = (SELECT COUNT(*) FROM voiceprint_embeddings WHERE person_id = ?), "
                "total_seconds = (SELECT COALESCE(SUM(seconds), 0) FROM voiceprint_embeddings "
                "WHERE person_id = ?) WHERE person_id = ?",
                (now, person.person_id, person.person_id, person.person_id),
            )
        return self.get(person.person_id)

    # -- deleting (always allowed) ---------------------------------------------------------------

    def delete_person(self, person_id: str) -> Person:
        person = self.get(person_id)
        with self.db.transaction() as conn:
            conn.execute(
                "DELETE FROM voiceprint_embeddings WHERE person_id = ?", (person.person_id,)
            )
            conn.execute("DELETE FROM voiceprints WHERE person_id = ?", (person.person_id,))
        self.db.checkpoint()
        log.info("Deleted the stored voice of one person")
        return person

    def wipe(self) -> dict[str, int]:
        """Delete every voiceprint; returns the number of rows removed per table."""
        counts = self.count_rows()
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM voiceprint_embeddings")
            conn.execute("DELETE FROM voiceprints")
        self.db.checkpoint()
        log.info("Deleted all stored voices (%d people)", counts["voiceprints"])
        return counts


# -- wipe confirmation ----------------------------------------------------------------------------

WIPE_TOKEN_SECONDS = 300.0


class WipeTokens:
    """Short-lived, single-use tokens that confirm "delete every voiceprint" (two-step wipe)."""

    def __init__(self, ttl: float = WIPE_TOKEN_SECONDS) -> None:
        self.ttl = ttl
        self._tokens: dict[str, float] = {}

    def issue(self, now: float) -> str:
        self._tokens = {t: exp for t, exp in self._tokens.items() if exp >= now}
        token = secrets.token_urlsafe(16)
        self._tokens[token] = now + self.ttl
        return token

    def consume(self, token: str | None, now: float) -> bool:
        if not token:
            return False
        expires = self._tokens.pop(token, None)
        return expires is not None and expires >= now
