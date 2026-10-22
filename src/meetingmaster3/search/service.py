"""The search index as an app service: one per server process (``app.state.search``).

It owns ``search.db``, runs index updates in the background and answers searches:

- **When it updates:** shortly after start-up (non-blocking), a couple of seconds after any vault
  write MM3 makes (``vault.changes``: note writing, review save, template switch, regeneration,
  rename, upgrade), every ``search.rescan_minutes`` (for edits made in Obsidian), from the
  Settings buttons and from ``mm3 search index``. Updates never overlap; a change during an
  update queues one more.
- **The GPU rule (R5):** with a local embedder each batch waits for the job runner's GPU, which
  is only handed out while no job is running or queued (``JobRunner.background_gpu``).
- **Progress:** the running update is a :class:`~meetingmaster3.review.progress.LongTask`
  (fraction, message, elapsed, time left, cancellable), like a template switch.

``Delete index`` removes ``search.db`` and its side files and switches ``search.enabled`` off,
so the index is not silently rebuilt; **Update** or **Rebuild** turns it on again.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sqlite3
import time
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from typing import Any

from meetingmaster3.config.paths import AppPaths
from meetingmaster3.config.settings import Settings
from meetingmaster3.errors import MM3Error
from meetingmaster3.llm.base import LLMBackend
from meetingmaster3.review.progress import LongTask, TaskState
from meetingmaster3.search.embedder import EmbedderChoice, resolve
from meetingmaster3.search.index import GpuGate, Indexer, UpdateReport
from meetingmaster3.search.query import Hit, MeetingFacts, Searcher, SearchFilters, SearchResult
from meetingmaster3.search.store import SearchStore, delete_index_files
from meetingmaster3.vault import changes
from meetingmaster3.vault.paths import is_inside, resolve_vault_root

log = logging.getLogger(__name__)

DEBOUNCE_S = 2.0
STALE_S = 60.0
"""A search starts a background check of the vault when the last one is older than this (an
unchanged file costs one ``stat``), so a note deleted or edited in Obsidian drops out soon."""
E_SEARCH_OFF = "E_SEARCH_OFF"


class RunnerGate:
    """The job runner's GPU, handed out only between jobs."""

    def __init__(self, runner: Any) -> None:
        self.runner = runner

    def hold(self) -> AbstractAsyncContextManager[None]:
        held: AbstractAsyncContextManager[None] = self.runner.background_gpu()
        return held


class JobsTableGate:
    """For the CLI, which cannot see the server's runner: wait until ``mm3.db`` shows no
    queued or running job (polled; the server's own gate does the same in-process)."""

    def __init__(self, database: Path, poll_s: float = 2.0) -> None:
        self.database = database
        self.poll_s = poll_s

    def busy(self) -> bool:
        if not self.database.exists():
            return False
        try:
            conn = sqlite3.connect(f"file:{self.database}?mode=ro", uri=True, timeout=5)
            try:
                row = conn.execute(
                    "SELECT COUNT(*) FROM jobs WHERE status IN ('queued', 'running')"
                ).fetchone()
            finally:
                conn.close()
        except sqlite3.Error:
            return False
        return bool(row and row[0])

    @asynccontextmanager
    async def hold(self) -> AsyncIterator[None]:
        while await asyncio.to_thread(self.busy):
            await asyncio.sleep(self.poll_s)
        yield


def vault_root(settings: Settings) -> Path | None:
    if settings.vault.path is None:
        return None
    try:
        return resolve_vault_root(settings.vault.path)
    except MM3Error:
        return None


class SearchService:
    def __init__(
        self,
        settings: Settings,
        paths: AppPaths,
        names: Callable[[], list[str]],
        lookup: Callable[[str], LLMBackend],
        gate: GpuGate | None = None,
    ) -> None:
        self.settings = settings
        self.paths = paths
        self._names = names
        self._lookup = lookup
        self.gate = gate
        self.store: SearchStore | None = None
        self.task: LongTask | None = None
        self.last_report: UpdateReport | None = None
        self._indexer: Indexer | None = None
        self._searcher: Searcher | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._wake: asyncio.Event | None = None
        self._pending_rebuild = False
        self._worker: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    # -- wiring ------------------------------------------------------------------------------

    def embedder(self) -> EmbedderChoice:
        return resolve(self.settings, self._names(), self._lookup)

    def _open(self) -> SearchStore:
        if self.store is None:
            self.store = SearchStore.open(self.paths.search_database)
            self._indexer = Indexer(self.store, self.settings, self.embedder, self.gate)
            self._searcher = Searcher(self.store, self.embedder)
        return self.store

    @property
    def indexer(self) -> Indexer:
        self._open()
        assert self._indexer is not None  # noqa: S101 - set by _open
        return self._indexer

    @property
    def searcher(self) -> Searcher:
        self._open()
        assert self._searcher is not None  # noqa: S101 - set by _open
        return self._searcher

    async def start(self) -> None:
        """Begin watching the vault and schedule the start-up scan (returns at once)."""
        self._loop = asyncio.get_running_loop()
        self._wake = asyncio.Event()
        changes.subscribe(self._on_change)
        self._worker = asyncio.create_task(self._run_forever(), name="mm3-search-index")
        if self.settings.search.enabled:
            self.schedule()

    async def stop(self) -> None:
        changes.unsubscribe(self._on_change)
        if self.task is not None and self.task.runner is not None:
            self.task.runner.cancel()
        if self._worker is not None:
            self._worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker
        if self.store is not None:
            self.store.close()
            self.store = None

    def _on_change(self, path: Path | None) -> None:
        """Called from any thread by vault writers; ignores files outside the vault."""
        root = vault_root(self.settings)
        if root is None or (path is not None and not is_inside(root, path)):
            return
        self.schedule()

    def schedule(self, *, rebuild: bool = False) -> None:
        """Ask for an update soon (thread-safe; repeated calls collapse into one)."""
        if not self.settings.search.enabled or self._loop is None or self._wake is None:
            return
        self._pending_rebuild = self._pending_rebuild or rebuild
        self._loop.call_soon_threadsafe(self._wake.set)

    async def _run_forever(self) -> None:
        assert self._wake is not None  # noqa: S101 - set by start
        while True:
            timeout = self.settings.search.rescan_minutes * 60.0
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout)
                await asyncio.sleep(DEBOUNCE_S)  # let a burst of writes finish first
            self._wake.clear()
            if not self.settings.search.enabled:
                continue
            rebuild, self._pending_rebuild = self._pending_rebuild, False
            try:
                task = self.start_update(rebuild=rebuild)
                if task.runner is not None:
                    with contextlib.suppress(asyncio.CancelledError):
                        await asyncio.shield(task.runner)
            except MM3Error as exc:
                log.info("Search index not updated: %s", exc.message)

    # -- updates -----------------------------------------------------------------------------

    def running(self) -> bool:
        return self.task is not None and self.task.state is TaskState.RUNNING

    def start_update(self, *, rebuild: bool = False) -> LongTask:
        """Start an update in the background (or return the one already running)."""
        if self.running():
            assert self.task is not None  # noqa: S101 - running() checked it
            if rebuild:
                self._pending_rebuild = True
                self.schedule(rebuild=True)
            return self.task
        root = vault_root(self.settings)
        if root is None:
            raise MM3Error(
                "E_VAULT_NOT_CONFIGURED",
                "There is no vault to index.",
                "Choose the vault in Settings → Vault first.",
                status_code=409,
            )
        task = LongTask(id="search-index", kind="rebuild" if rebuild else "update", mm3_id="")
        task.message = "Rebuilding the index" if rebuild else "Updating the index"

        async def work() -> None:
            async with self._lock:
                store = await asyncio.to_thread(self._open)
                if rebuild:
                    await asyncio.to_thread(store.clear)
                self.last_report = await self.indexer.update(root, task.update)
            task.result = self.last_report

        async def run() -> None:
            try:
                await work()
            except asyncio.CancelledError:
                task.finish(TaskState.CANCELLED)
                return
            except MM3Error as exc:
                task.error = exc
                task.finish(TaskState.FAILED)
                return
            except Exception as exc:
                log.exception("Search index update failed")
                task.error = MM3Error("E_SEARCH_INDEX", f"The index update failed: {exc}", "")
                task.finish(TaskState.FAILED)
                return
            task.update(1.0, "Done")
            task.finish(TaskState.DONE)

        self.task = task
        task.runner = asyncio.get_running_loop().create_task(run(), name="mm3-search-update")
        return task

    async def update_now(self, *, rebuild: bool = False) -> UpdateReport | None:
        """Run an update and wait for it (tests, and the CLI through the same code)."""
        task = self.start_update(rebuild=rebuild)
        if task.runner is not None:
            await task.runner
        if task.error is not None:
            raise task.error
        return self.last_report

    async def cancel(self) -> None:
        if self.running() and self.task is not None and self.task.runner is not None:
            self.task.runner.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task.runner

    async def delete_index(self) -> list[Path]:
        """Remove the index files and switch indexing off (see the module doc)."""
        await self.cancel()
        async with self._lock:
            if self.store is not None:
                self.store.close()
            self.store, self._indexer, self._searcher = None, None, None
            removed = await asyncio.to_thread(delete_index_files, self.paths.search_database)
        self.settings.search.enabled = False
        self.last_report = None
        self.task = None
        return removed

    def enable(self) -> None:
        self.settings.search.enabled = True

    # -- searching ---------------------------------------------------------------------------

    async def query(
        self, text: str, *, limit: int = 20, filters: SearchFilters | None = None
    ) -> SearchResult:
        if not self.settings.search.enabled:
            raise MM3Error(
                E_SEARCH_OFF,
                "Search is switched off.",
                "Turn it on in Settings → Search & Ask (Update index).",
                status_code=409,
            )
        await asyncio.to_thread(self._open)
        self._refresh_if_stale()
        return await self.searcher.query(text, limit=limit, filters=filters)

    def _refresh_if_stale(self) -> None:
        if self.running() or self._loop is None:
            return
        finished = self.task.finished if self.task is not None else None
        if finished is None or time.monotonic() - finished > STALE_S:
            self.schedule()

    async def meeting_facts(
        self, mm3_ids: list[str], hits: list[Hit] | None = None
    ) -> dict[str, MeetingFacts]:
        await asyncio.to_thread(self._open)
        return await asyncio.to_thread(self.searcher.meeting_facts, mm3_ids, hits or [])

    # -- status ------------------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """What the Settings card and ``mm3 search status`` show."""
        exists = self.paths.search_database.exists()
        stats = self.store.stats() if self.store is not None and exists else None
        if stats is None and exists:
            stats = self._open().stats()
        embedder: dict[str, Any] = {}
        try:
            choice = self.embedder()
            embedder = {
                "backend": choice.backend_name,
                "model": choice.model,
                "badge": choice.badge,
                "consented": choice.consented,
                "model_id": choice.model_id,
            }
        except MM3Error as exc:
            embedder = {"error": exc.message, "hint": exc.hint}
        meta = stats.meta if stats else {}
        vectors_ok = bool(stats and stats.passages and stats.vectors >= stats.passages)
        report = self.last_report
        return {
            "enabled": self.settings.search.enabled,
            "exists": exists,
            "path": str(self.paths.search_database),
            "meetings": stats.meetings if stats else 0,
            "notes": stats.notes if stats else 0,
            "transcripts": stats.transcripts if stats else 0,
            "passages": stats.passages if stats else 0,
            "vectors": stats.vectors if stats else 0,
            "vectors_complete": vectors_ok,
            "size_bytes": stats.size_bytes if stats else 0,
            "last_update": meta.get("last_update"),
            "last_seconds": meta.get("last_seconds"),
            "indexed_model": meta.get("embed_model"),
            "dims": meta.get("dims"),
            "vector_error": meta.get("vector_error"),
            "vector_error_code": meta.get("vector_error_code"),
            "failed": [{"path": p, "message": m} for p, m in report.failed] if report else [],
            "failed_count": int(meta.get("failed") or 0),
            "truncated": bool(meta.get("truncated")),
            "embedder": embedder,
            "task": self.task.snapshot() if self.task is not None else None,
            "running": self.running(),
        }
