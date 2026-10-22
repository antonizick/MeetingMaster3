"""Keeping ``search.db`` in step with the vault (Phase 15i)."""

from __future__ import annotations

import asyncio
import os
import stat
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from meetingmaster3.config.settings import Settings
from meetingmaster3.llm.base import E_CONSENT_REQUIRED
from meetingmaster3.llm.fake import FakeLLMBackend
from meetingmaster3.search.embedder import EmbedderChoice, resolve
from meetingmaster3.search.index import Indexer
from meetingmaster3.search.store import SearchStore, delete_index_files
from tests.search_corpus import MEETINGS, MEETINGS_DIR, by_key
from tests.unit.search.conftest import cloud_settings

FINANCE = f"{MEETINGS_DIR}/{by_key('finance').stem}.md"


async def test_full_index_of_the_corpus(
    indexer: Indexer, store: SearchStore, corpus_vault: Path
) -> None:
    report = await indexer.update(corpus_vault)
    assert (report.added, report.failed, report.vector_error) == (14, [], None)
    stats = store.stats()
    assert (stats.meetings, stats.notes, stats.transcripts) == (7, 7, 7)
    assert stats.passages == stats.vectors > 14
    assert store.get_meta("embed_model") == "ollama:nomic-embed-text"
    assert store.get_meta("dims") == "64"
    # A transcript takes its date and title from its note.
    docs = {d.path: d for d in store.documents()}
    t = docs[f"{MEETINGS_DIR}/{by_key('vendor').stem}.transcript.md"]
    assert (t.title, t.date, t.speakers) == (
        "Vendor Contract Sync",
        "2026-09-16",
        ("Dana Whitfield", "Mei Lin"),
    )


async def test_the_index_file_is_private(store: SearchStore) -> None:
    assert store.path is not None
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    assert store.fetchone("PRAGMA secure_delete")[0] == 1  # type: ignore[index]


async def test_files_that_are_not_meetings_are_skipped(
    indexer: Indexer, store: SearchStore, corpus_vault: Path, tmp_path: Path
) -> None:
    mid = "00000000-0000-4000-8000-000000000555"
    extra = {
        "Readable (Transcript).md": (
            f"---\nmm3-id: {mid}\nmm3-kind: readable-transcript\n---\nbudget\n"
        ),
        "Archive.md": f"---\nmm3-id: {mid}\nmm3-archived: 2026-09-01\ntitle: Old\n---\nbudget\n",
        "MM3 Answers/Answer.md": f"---\nmm3-id: {mid}\nmm3-kind: answer\ntitle: A\n---\nbudget\n",
        "Plain note.md": "# My notes\nbudget overrun everywhere\n",
        ".trash/Deleted.md": f"---\nmm3-id: {mid}\ntitle: Gone\n---\n# Gone\n",
        "_hidden/.secret.md": f"---\nmm3-id: {mid}\ntitle: Hidden\n---\n# Hidden\n",
    }
    for rel, text in extra.items():
        path = corpus_vault / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    outside = tmp_path / "outside.md"
    outside.write_text(f"---\nmm3-id: {mid}\ntitle: Outside\n---\n# Outside\n", encoding="utf-8")
    os.symlink(outside, corpus_vault / "Linked.md")
    os.symlink(tmp_path, corpus_vault / "linked-folder", target_is_directory=True)
    report = await indexer.update(corpus_vault)
    assert report.added == 14 and report.failed == []
    assert {d.mm3_id for d in store.documents()} == {str(m.id) for m in MEETINGS}


async def test_incremental_update_reindexes_only_what_changed(
    indexer: Indexer, store: SearchStore, corpus_vault: Path, fake: FakeLLMBackend
) -> None:
    await indexer.update(corpus_vault)
    again = await indexer.update(corpus_vault)
    assert (again.changed, again.unchanged, again.embedded) == (0, 14, 0)
    note = corpus_vault / FINANCE
    text = note.read_text(encoding="utf-8")
    note.write_text(
        text.replace("contractor fees.", "contractor fees and travel."), encoding="utf-8"
    )
    fake.embed_calls.clear()
    report = await indexer.update(corpus_vault)
    assert (report.updated, report.unchanged) == (1, 13)
    # Only the edited section's passage was embedded again; the others kept their vectors.
    assert report.embedded == 1
    assert "travel" in fake.embed_calls[0][1][0]
    stats = store.stats()
    assert stats.vectors == stats.passages


async def test_a_touched_but_unchanged_file_is_not_reindexed(
    indexer: Indexer, store: SearchStore, corpus_vault: Path
) -> None:
    await indexer.update(corpus_vault)
    os.utime(corpus_vault / FINANCE, ns=(1, 1))
    report = await indexer.update(corpus_vault)
    assert (report.changed, report.unchanged, report.embedded) == (0, 14, 0)


async def test_a_deleted_meeting_drops_out(
    indexer: Indexer, store: SearchStore, corpus_vault: Path
) -> None:
    await indexer.update(corpus_vault)
    (corpus_vault / FINANCE).unlink()
    report = await indexer.update(corpus_vault)
    assert report.removed == 1
    assert FINANCE not in {d.path for d in store.documents()}
    assert (
        store.fetchone(
            "SELECT COUNT(*) FROM vectors v LEFT JOIN passages p ON p.id = v.passage_id "
            "WHERE p.id IS NULL"
        )[0]
        == 0
    )  # type: ignore[index]


async def test_a_moved_file_keeps_its_vectors(
    indexer: Indexer, store: SearchStore, corpus_vault: Path, fake: FakeLLMBackend
) -> None:
    await indexer.update(corpus_vault)
    target = corpus_vault / "Archive 2026" / "Q3 Finance Review.md"
    target.parent.mkdir()
    (corpus_vault / FINANCE).rename(target)
    fake.embed_calls.clear()
    report = await indexer.update(corpus_vault)
    assert (report.moved, report.added, report.removed, report.embedded) == (1, 0, 0, 0)
    assert fake.embed_calls == []
    paths = {d.path for d in store.documents()}
    assert "Archive 2026/Q3 Finance Review.md" in paths and FINANCE not in paths


async def test_a_different_embedding_model_replaces_every_vector(
    indexer: Indexer, store: SearchStore, corpus_vault: Path, search_settings: Settings
) -> None:
    await indexer.update(corpus_vault)
    passages = store.stats().passages
    search_settings.search.embedding_model = "bge-m3"
    report = await indexer.update(corpus_vault)
    assert report.embedded == passages
    models = {r[0] for r in store.fetchall("SELECT DISTINCT model FROM vectors")}
    assert models == {"ollama:bge-m3"}
    assert store.get_meta("embed_model") == "ollama:bge-m3"


async def test_cloud_embedder_without_consent_sends_nothing(
    store: SearchStore, search_settings: Settings, corpus_vault: Path
) -> None:
    cloud = FakeLLMBackend(id="router", kind="openrouter", is_local=False)
    settings = cloud_settings(search_settings, consent=False)
    idx = Indexer(store, settings, lambda: resolve(settings, ["ollama", "router"], lambda n: cloud))
    report = await idx.update(corpus_vault)
    assert cloud.embed_calls == []
    assert report.vector_error is not None and report.vector_error.code == E_CONSENT_REQUIRED
    stats = store.stats()
    assert stats.passages > 0 and stats.vectors == 0  # the word index is still complete
    assert "cloud service" in (store.get_meta("vector_error") or "")
    settings.llm.backends["router"].cloud_embedding_consent = True
    report = await idx.update(corpus_vault)
    assert report.vector_error is None and cloud.embed_calls
    assert store.stats().vectors == stats.passages


async def test_an_unavailable_embedder_leaves_a_word_index(
    store: SearchStore, search_settings: Settings, corpus_vault: Path
) -> None:
    from meetingmaster3.errors import MM3Error

    class Down(FakeLLMBackend):
        async def embed(
            self, model: str, texts: object, *, purpose: str = "document"
        ) -> list[list[float]]:  # type: ignore[override]
            raise MM3Error("E_LLM_UNREACHABLE", "Cannot reach Ollama.", "Start Ollama.")

    down = Down(id="ollama", kind="ollama")
    idx = Indexer(
        store, search_settings, lambda: resolve(search_settings, ["ollama"], lambda n: down)
    )
    report = await idx.update(corpus_vault)
    assert report.vector_error is not None and report.vector_error.code == "E_LLM_UNREACHABLE"
    assert store.stats().vectors == 0 and store.stats().passages > 0
    assert store.get_meta("vector_error_code") == "E_LLM_UNREACHABLE"


async def test_turning_transcripts_off_removes_them(
    indexer: Indexer, store: SearchStore, corpus_vault: Path, search_settings: Settings
) -> None:
    await indexer.update(corpus_vault)
    search_settings.search.index_transcripts = False
    report = await indexer.update(corpus_vault)
    assert report.removed == 7
    assert {d.kind for d in store.documents()} == {"note"}


async def test_a_broken_companion_is_reported_not_fatal(
    indexer: Indexer, corpus_vault: Path
) -> None:
    bad = corpus_vault / MEETINGS_DIR / "Broken.transcript.md"
    bad.write_text(
        "---\nmm3-id: 00000000-0000-4000-8000-000000000777\n---\nno data block\n", encoding="utf-8"
    )
    report = await indexer.update(corpus_vault)
    assert report.added == 14
    assert [p for p, _ in report.failed] == [f"{MEETINGS_DIR}/Broken.transcript.md"]


async def test_local_embedding_waits_for_the_gpu_gate(
    store: SearchStore,
    search_settings: Settings,
    corpus_vault: Path,
    embedder: Callable[[], EmbedderChoice],
    fake: FakeLLMBackend,
) -> None:
    held = asyncio.Event()
    release = asyncio.Event()
    entered = 0

    class Gate:
        @asynccontextmanager
        async def hold(self) -> AsyncIterator[None]:
            nonlocal entered
            held.set()
            await release.wait()
            entered += 1
            yield

    idx = Indexer(store, search_settings, embedder, Gate())
    task = asyncio.create_task(idx.update(corpus_vault))
    await asyncio.wait_for(held.wait(), 5)
    assert fake.embed_calls == []  # nothing is embedded while the gate is closed
    release.set()
    report = await asyncio.wait_for(task, 5)
    assert report.embedded > 0 and entered >= 1


def test_delete_index_files_removes_side_files(tmp_path: Path) -> None:
    db = tmp_path / "search.db"
    s = SearchStore.open(db)
    s.set_meta(x="1")
    s.close()
    (tmp_path / "search.db-wal").write_bytes(b"")
    removed = delete_index_files(db)
    assert db in removed and not db.exists() and not (tmp_path / "search.db-wal").exists()


def test_an_index_of_another_schema_version_is_rebuilt(tmp_path: Path) -> None:
    import sqlite3

    db = tmp_path / "search.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE documents (x)")
    conn.execute("PRAGMA user_version = 99")
    conn.commit()
    conn.close()
    s = SearchStore.open(db)
    assert s.fetchone("PRAGMA user_version")[0] == 1  # type: ignore[index]
    assert s.stats().documents == 0
    s.close()


@pytest.mark.parametrize("bad", ["", "   "])
async def test_an_empty_vault_indexes_nothing(
    tmp_path: Path, bad: str, store: SearchStore, search_settings: Settings
) -> None:
    root = tmp_path / ("empty" + bad.strip())
    root.mkdir()
    report = await Indexer(store, search_settings).update(root)
    assert (report.added, report.removed) == (0, 0)
