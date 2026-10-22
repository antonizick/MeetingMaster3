from __future__ import annotations

import shutil
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from meetingmaster3.config.settings import BackendConfig, Settings
from meetingmaster3.llm.fake import FakeLLMBackend
from meetingmaster3.search.embedder import EmbedderChoice, resolve
from meetingmaster3.search.index import Indexer
from meetingmaster3.search.query import Searcher
from meetingmaster3.search.store import SearchStore
from tests.search_corpus import FOLDER


@pytest.fixture
def corpus_vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    shutil.copytree(FOLDER, root)
    return root.resolve()


@pytest.fixture
def search_settings(corpus_vault: Path) -> Settings:
    s = Settings()
    s.vault.path = corpus_vault
    s.search.enabled = True
    return s


@pytest.fixture
def fake() -> FakeLLMBackend:
    return FakeLLMBackend(id="ollama", kind="ollama")


@pytest.fixture
def embedder(search_settings: Settings, fake: FakeLLMBackend) -> Callable[[], EmbedderChoice]:
    return lambda: resolve(search_settings, ["ollama"], lambda name: fake)


@pytest.fixture
def store(tmp_path: Path) -> Iterator[SearchStore]:
    s = SearchStore.open(tmp_path / "data" / "search.db")
    yield s
    s.close()


@pytest.fixture
def indexer(
    store: SearchStore, search_settings: Settings, embedder: Callable[[], EmbedderChoice]
) -> Indexer:
    return Indexer(store, search_settings, embedder)


@pytest.fixture
def searcher(store: SearchStore, embedder: Callable[[], EmbedderChoice]) -> Searcher:
    return Searcher(store, embedder)


def cloud_settings(settings: Settings, *, consent: bool) -> Settings:
    settings.llm.backends["router"] = BackendConfig(
        kind="openrouter", cloud_embedding_consent=consent
    )
    settings.search.embedding_backend = "router"
    return settings
