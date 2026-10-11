"""The voiceprint store: CRUD, caps, model isolation, the disabled path and a verified wipe."""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from meetingmaster3.errors import MM3Error
from meetingmaster3.speakers.store import VoiceprintStore, WipeTokens, check_person_id
from meetingmaster3.speakers.vectors import normalize, to_blob
from meetingmaster3.storage.db import Database
from meetingmaster3.storage.migrations import MIGRATIONS, migrate

MODEL = "test/embedding@1"


def vec(seed: int, dim: int = 64) -> list[float]:
    rng = random.Random(seed)  # noqa: S311 - test data
    return normalize([rng.gauss(0, 1) for _ in range(dim)])


@pytest.fixture
def db(tmp_path: Path) -> Database:
    return Database.open(tmp_path / "mm3.db")


@pytest.fixture
def store(db: Database) -> VoiceprintStore:
    return VoiceprintStore(db, enabled=True, max_embeddings=3)


def test_migration_2_upgrades_a_version_1_database(tmp_path: Path) -> None:
    import sqlite3

    conn = sqlite3.connect(tmp_path / "old.db", isolation_level=None)
    assert migrate(conn, MIGRATIONS[:1]) == 1
    assert migrate(conn) == len(MIGRATIONS) >= 2
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"voiceprints", "voiceprint_embeddings"} <= tables


def test_create_list_rename_find(store: VoiceprintStore) -> None:
    alice = store.create_person("  Alice   Smith ")
    assert alice.display_name == "Alice Smith" and alice.n_samples == 0
    bob = store.create_person("bob")
    assert [p.display_name for p in store.list_people()] == ["Alice Smith", "bob"]
    assert store.get(alice.person_id) == alice
    assert store.find("not-a-uuid") is None
    assert store.find(bob.person_id.upper()) is not None  # ids are normalised
    assert [p.person_id for p in store.find_by_name("ALICE smith")] == [alice.person_id]
    renamed = store.rename(bob.person_id, "Robert")
    assert renamed.display_name == "Robert"
    with pytest.raises(MM3Error) as err:
        store.get("0" * 32)
    assert err.value.code == "E_PERSON_NOT_FOUND" and err.value.status_code == 404
    for bad in ("", "   ", "x" * 201):
        with pytest.raises(MM3Error, match="1 to 200"):
            store.create_person(bad)
        with pytest.raises(MM3Error, match="1 to 200"):
            store.rename(alice.person_id, bad)
    with pytest.raises(MM3Error):
        check_person_id("../../etc")


def test_public_view_never_contains_vectors(store: VoiceprintStore) -> None:
    p = store.create_person("Alice")
    store.add_embedding(p.person_id, vec(1), model_id=MODEL, seconds=40, source_job_id="j1")
    view = store.get(p.person_id).to_dict()
    assert set(view) == {
        "person_id", "name", "created_at", "last_seen", "samples", "total_seconds", "models",
    }  # fmt: skip
    assert view["samples"] == 1 and view["total_seconds"] == 40.0 and view["models"] == [MODEL]


def test_embeddings_are_capped_and_idempotent_per_job(store: VoiceprintStore) -> None:
    p = store.create_person("Alice")
    for i in range(5):
        store.add_embedding(p.person_id, vec(i), model_id=MODEL, seconds=10, source_job_id=f"j{i}")
    people = store.known_people(MODEL)
    assert len(people) == 1 and len(people[0].embeddings) == 3  # newest 3 kept
    assert people[0].embeddings[-1] == pytest.approx(vec(4), abs=1e-6)
    # Re-enrolling from the same job replaces its embedding instead of adding one.
    store.add_embedding(p.person_id, vec(99), model_id=MODEL, seconds=12, source_job_id="j4")
    person = store.get(p.person_id)
    assert person.n_samples == 3 and person.total_seconds == 32.0
    assert store.known_people(MODEL)[0].embeddings[-1] == pytest.approx(vec(99), abs=1e-6)


def test_model_ids_are_never_mixed(store: VoiceprintStore) -> None:
    alice = store.create_person("Alice")
    bob = store.create_person("Bob")
    store.add_embedding(alice.person_id, vec(1), model_id=MODEL, seconds=30, source_job_id="j")
    store.add_embedding(bob.person_id, vec(2), model_id="other/model@2", seconds=30,
                        source_job_id="j")  # fmt: skip
    assert [p.display_name for p in store.known_people(MODEL)] == ["Alice"]
    assert [p.display_name for p in store.known_people("other/model@2")] == ["Bob"]
    assert store.known_people("unknown") == []


def test_disabled_store_persists_nothing(db: Database) -> None:
    """Acceptance: with voiceprints disabled (the default) no rows are written."""
    store = VoiceprintStore(db, enabled=False)
    with pytest.raises(MM3Error) as err:
        store.create_person("Alice")
    assert err.value.code == "E_VOICEPRINTS_DISABLED"
    enabled = VoiceprintStore(db, enabled=True)
    p = enabled.create_person("Alice")
    with pytest.raises(MM3Error):
        store.add_embedding(p.person_id, vec(1), model_id=MODEL, seconds=1, source_job_id=None)
    assert store.count_rows() == {"voiceprints": 1, "voiceprint_embeddings": 0}
    enabled.add_embedding(p.person_id, vec(1), model_id=MODEL, seconds=1, source_job_id=None)
    assert store.known_people(MODEL) == []  # disabled: stored voices are not used either
    assert store.list_people()  # but they can still be listed and deleted
    store.delete_person(p.person_id)
    assert store.count_rows() == {"voiceprints": 0, "voiceprint_embeddings": 0}


def test_delete_person_cascades(store: VoiceprintStore) -> None:
    alice = store.create_person("Alice")
    bob = store.create_person("Bob")
    for p in (alice, bob):
        store.add_embedding(p.person_id, vec(3), model_id=MODEL, seconds=5, source_job_id="j")
    deleted = store.delete_person(alice.person_id)
    assert deleted.display_name == "Alice"
    assert store.count_rows() == {"voiceprints": 1, "voiceprint_embeddings": 1}
    with pytest.raises(MM3Error):
        store.delete_person(alice.person_id)


def test_wipe_removes_everything_from_the_database_file(tmp_path: Path) -> None:
    """Acceptance: wipe removes everything, verified at the DB level (rows, file and WAL)."""
    path = tmp_path / "mm3.db"
    db = Database.open(path)
    store = VoiceprintStore(db, enabled=True)
    blobs = []
    for i in range(4):
        p = store.create_person(f"Zyxwvut Person {i}")
        v = vec(100 + i, dim=256)
        blobs.append(to_blob(v))
        store.add_embedding(p.person_id, v, model_id=MODEL, seconds=30, source_job_id=f"j{i}")
    db.checkpoint()
    assert any(b[:64] in path.read_bytes() for b in blobs)  # the test can see them before

    assert store.wipe() == {"voiceprints": 4, "voiceprint_embeddings": 4}
    assert store.count_rows() == {"voiceprints": 0, "voiceprint_embeddings": 0}
    assert db.fetchone("SELECT COUNT(*) FROM voiceprint_embeddings")[0] == 0  # type: ignore[index]
    db.close()
    data = path.read_bytes()
    wal = path.with_name("mm3.db-wal")
    data += wal.read_bytes() if wal.exists() else b""
    for b in blobs:
        assert b[:64] not in data  # secure_delete zeroed the pages; the WAL was truncated
    assert b"Zyxwvut" not in data


def test_wipe_tokens_are_single_use_and_expire() -> None:
    tokens = WipeTokens(ttl=10)
    t = tokens.issue(now=0)
    assert not tokens.consume(None, now=1) and not tokens.consume("guess", now=1)
    assert tokens.consume(t, now=5)
    assert not tokens.consume(t, now=5)  # used
    old = tokens.issue(now=0)
    assert not tokens.consume(old, now=11)  # expired
    stale = tokens.issue(now=0)
    tokens.issue(now=20)  # issuing purges expired tokens
    assert stale not in tokens._tokens
