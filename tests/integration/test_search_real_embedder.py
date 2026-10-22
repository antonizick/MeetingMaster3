"""The search corpus with a real local embedder (``nomic-embed-text`` through Ollama).

Marked ``models``: needs a running Ollama with the model pulled; skipped otherwise and in CI.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import httpx
import pytest

from meetingmaster3.config.settings import Settings
from meetingmaster3.llm.ollama import OllamaBackend
from meetingmaster3.search.embedder import resolve
from meetingmaster3.search.index import Indexer
from meetingmaster3.search.query import Searcher
from meetingmaster3.search.store import SearchStore
from tests.search_corpus import FOLDER, TOPIC, by_key

pytestmark = pytest.mark.models

MODEL = "nomic-embed-text"


def _available() -> bool:
    try:
        tags = httpx.get("http://127.0.0.1:11434/api/tags", timeout=2).json()
    except (httpx.HTTPError, ValueError):
        return False
    return any(m.get("name", "").startswith(MODEL) for m in tags.get("models", []))


async def test_meaning_question_finds_the_topic_in_three_wordings(tmp_path: Path) -> None:
    if not _available():
        pytest.skip(f"Ollama with {MODEL} is not available")
    vault = tmp_path / "vault"
    shutil.copytree(FOLDER, vault)
    settings = Settings()
    settings.search.embedding_model = MODEL
    backend = OllamaBackend()
    choice = lambda: resolve(settings, ["ollama"], lambda name: backend)  # noqa: E731
    store = SearchStore.open(tmp_path / "search.db")
    report = await Indexer(store, settings, choice).update(vault)
    assert report.vector_error is None and report.vectors_missing == 0
    searcher = Searcher(store, choice)
    result = await searcher.query("Where did we spend more money than we expected?", limit=30)
    assert result.mode == "hybrid"
    top = [m.mm3_id for m in result.group_by_meeting()[:3]]
    assert set(top) == {str(by_key(k).id) for k in TOPIC}
    words = await searcher.query(
        "Where did we spend more money than we expected?", use_vectors=False
    )
    assert len(words.group_by_meeting()) < 3  # the words alone miss at least one
    store.close()
