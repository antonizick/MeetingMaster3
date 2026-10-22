"""Which backend and model embed passages and queries, and the cloud-consent rule (ADR-0049).

The embedder is ``search.embedding_backend`` (default: the local Ollama, else the first local
backend) with ``search.embedding_model``. A cloud embedder needs that backend's
``cloud_embedding_consent``: indexing sends every meeting's text, and each search sends the query.
Without it nothing is sent and the index keeps only its word index.

Some embedding models are trained with task prefixes and work noticeably worse without them
(nomic-embed-text: ``search_document:`` / ``search_query:``); :func:`prefixes` knows them.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from meetingmaster3.config.settings import Settings
from meetingmaster3.errors import MM3Error
from meetingmaster3.llm.base import (
    E_CONSENT_REQUIRED,
    Embedder,
    LLMBackend,
    embed_unsupported,
    llm_error,
    supports_embeddings,
)

E_SEARCH_NO_EMBEDDER = "E_SEARCH_NO_EMBEDDER"

_PREFIXES: tuple[tuple[str, str, str], ...] = (
    ("nomic-embed-text", "search_document: ", "search_query: "),
    ("nomic-ai/nomic-embed", "search_document: ", "search_query: "),
    ("mxbai-embed-large", "", "Represent this sentence for searching relevant passages: "),
    ("snowflake-arctic-embed", "", "Represent this sentence for searching relevant passages: "),
    (
        "qwen3-embedding",
        "",
        "Instruct: Given a question, retrieve meeting passages that answer it\nQuery: ",
    ),
    ("e5-", "passage: ", "query: "),
)
"""``(model-name fragment, document prefix, query prefix)``; the first fragment found wins."""


def prefixes(model: str) -> tuple[str, str]:
    """The (document, query) prefixes ``model`` expects; ``("", "")`` for most models."""
    low = model.lower()
    for fragment, doc, query in _PREFIXES:
        if fragment in low:
            return doc, query
    return "", ""


@dataclass(frozen=True)
class EmbedderChoice:
    backend_name: str
    backend: Any
    """An :class:`~meetingmaster3.llm.base.Embedder` (typed loosely: backends are duck-typed)."""
    kind: str
    model: str
    is_local: bool
    consented: bool
    """True for a local backend, or a cloud one with ``cloud_embedding_consent``."""

    @property
    def model_id(self) -> str:
        """What a stored vector is tagged with; a different id means re-embedding."""
        return f"{self.kind}:{self.model}"

    @property
    def badge(self) -> str:
        return "local" if self.is_local else f"cloud: {self.kind}"

    def require_consent(self) -> None:
        if not self.consented:
            raise llm_error(
                E_CONSENT_REQUIRED,
                f"Searching with '{self.backend_name}' would send the text of every meeting (and "
                "each search) to a cloud service, and that has not been allowed.",
                "Allow it in Settings → Language models → edit the backend (“Allow search "
                "indexing”), or use the local Ollama embedder.",
                status_code=403,
            )

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.require_consent()
        doc, _ = prefixes(self.model)
        embedder: Embedder = self.backend
        return await embedder.embed(self.model, [doc + t for t in texts], purpose="document")

    async def embed_query(self, text: str) -> list[float]:
        self.require_consent()
        _, query = prefixes(self.model)
        embedder: Embedder = self.backend
        vectors = await embedder.embed(self.model, [query + text], purpose="query")
        return vectors[0]


BackendLookup = Callable[[str], LLMBackend]


def default_backend_name(settings: Settings, names: Sequence[str], lookup: BackendLookup) -> str:
    """``search.embedding_backend``, else ``ollama``, else the first local backend with
    embeddings."""
    if settings.search.embedding_backend:
        return settings.search.embedding_backend
    if "ollama" in names:
        return "ollama"
    for name in names:
        try:
            backend = lookup(name)
        except MM3Error:
            continue
        if backend.is_local and supports_embeddings(backend):
            return name
    raise MM3Error(
        E_SEARCH_NO_EMBEDDER,
        "No local backend can embed passages for search.",
        "Add the local Ollama backend and run `ollama pull nomic-embed-text`, or choose an "
        "embedding backend in Settings → Search & Ask.",
        status_code=400,
    )


def resolve(settings: Settings, names: Sequence[str], lookup: BackendLookup) -> EmbedderChoice:
    """The configured embedder. Raises ``MM3Error`` if the backend is unknown or cannot embed."""
    name = default_backend_name(settings, names, lookup)
    backend = lookup(name)
    if not supports_embeddings(backend):
        raise embed_unsupported(f"The backend '{name}'")
    cfg = settings.llm.backends.get(name)
    consent = backend.is_local or bool(cfg and cfg.cloud_embedding_consent)
    return EmbedderChoice(
        backend_name=name,
        backend=backend,
        kind=str(getattr(backend, "kind", "unknown")),
        model=settings.search.embedding_model,
        is_local=backend.is_local,
        consented=consent,
    )
