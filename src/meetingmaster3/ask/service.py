"""The Ask AI agent as an app service (``app.state.ask``; the CLI builds its own).

It chooses the backend and model, checks consent, runs the agent
(:class:`~meetingmaster3.ask.pipeline.AskAgent`) as a long task (one question at a time), saves each
finished answer as a vault note plus a history row, and finds, lists and deletes answers.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from meetingmaster3.ask.notes import (
    SavedAnswer,
    delete_answer_note,
    new_answer_id,
    resolve_answer,
    write_answer_note,
)
from meetingmaster3.ask.pipeline import (
    AskAgent,
    AskResult,
    Gate,
    SearchRetriever,
    enforce_ask_consent,
    meeting_context_from,
)
from meetingmaster3.ask.store import AnswerRecord, AnswerStore, SourceRef
from meetingmaster3.config.settings import BackendConfig, Settings
from meetingmaster3.errors import MM3Error
from meetingmaster3.llm.base import LLMBackend
from meetingmaster3.llm.consent import requires_consent
from meetingmaster3.review.progress import LongTask, TaskRegistry, TaskState
from meetingmaster3.search.query import SearchFilters
from meetingmaster3.storage.db import Database
from meetingmaster3.vault.io import read_text
from meetingmaster3.vault.paths import confine, resolve_vault_root

log = logging.getLogger(__name__)

TASK_KEY = "ask"
E_ASK_RUNNING = "E_ASK_RUNNING"
E_ASK_NO_MODEL = "E_ASK_NO_MODEL"
E_ASK_NOT_FOUND = "E_ASK_NOT_FOUND"
WILDCARD_HOSTS = frozenset({"0.0.0.0", "::", ""})  # noqa: S104 - compared, never bound


def base_url(settings: Settings) -> str:
    """Where MeetingMaster3 answers, for links written into answer notes."""
    host = settings.server.host
    host = "127.0.0.1" if host in WILDCARD_HOSTS else host
    if ":" in host:
        host = f"[{host}]"
    return f"http://{host}:{settings.server.port}"


@dataclass(frozen=True)
class Choice:
    """The backend and model that will answer."""

    name: str
    backend: LLMBackend
    model: str
    config: BackendConfig | None

    @property
    def is_local(self) -> bool:
        return self.backend.is_local

    @property
    def remembered(self) -> bool:
        return bool(self.config and self.config.ask_consent_remembered)

    @property
    def needs_consent(self) -> bool:
        return requires_consent(self.backend) and not self.remembered


@dataclass
class Located:
    record: AnswerRecord
    path: Path | None
    """``None``: the note is not in the vault any more (deleted or moved out of it)."""
    moved: bool = False


class AskService:
    def __init__(
        self,
        settings: Settings,
        db: Database,
        search: Any,
        lookup: Callable[[str], LLMBackend],
        names: Callable[[], list[str]],
        gate: Gate | None = None,
    ) -> None:
        self.settings = settings
        self.db = db
        self.search = search
        self._lookup = lookup
        self._names = names
        self.gate = gate
        self.tasks = TaskRegistry()
        self.store = AnswerStore(db)

    # -- choosing -----------------------------------------------------------------------

    def vault_root(self) -> Path:
        if self.settings.vault.path is None:
            raise MM3Error(
                "E_VAULT_NOT_CONFIGURED",
                "There is no vault to answer from.",
                "Choose the vault in Settings → Vault first.",
                status_code=409,
            )
        return resolve_vault_root(self.settings.vault.path)

    def default_backend(self) -> str:
        names = self._names()
        for name in (self.settings.ask.default_backend, self.settings.llm.default_backend):
            if name and name in names:
                return name
        return names[0] if names else self.settings.llm.default_backend

    def choose(self, backend: str | None = None, model: str | None = None) -> Choice:
        name = backend or self.default_backend()
        if name not in self._names():
            raise MM3Error(
                "E_LLM_UNKNOWN_BACKEND", f"No backend named '{name}'.", "", status_code=404
            )
        llm = self._lookup(name)
        cfg = self.settings.llm.backends.get(name)
        chosen = (model or "").strip()
        if not chosen and name == self.default_backend() and self.settings.ask.default_model:
            chosen = self.settings.ask.default_model
        if not chosen:
            chosen = (cfg.default_model if cfg else None) or ""
        if not chosen and getattr(llm, "kind", "") == "fake":
            chosen = "fake-model"
        if not chosen:
            raise MM3Error(
                E_ASK_NO_MODEL,
                f"No model is chosen for '{name}'.",
                "Pick a model, or set the backend's default model in Settings → Language models.",
                status_code=422,
            )
        return Choice(name, llm, chosen, cfg)

    # -- running ------------------------------------------------------------------------

    def _agent(
        self,
        choice: Choice,
        *,
        cloud_consent: bool,
        filters: SearchFilters,
        previous: AnswerRecord | None,
        progress: Callable[[float, str], None] | None = None,
    ) -> AskAgent:
        root = self.vault_root()

        async def context(note_path: str) -> str | None:
            def load() -> str | None:
                return meeting_context_from(read_text(confine(root, note_path)))

            return await asyncio.to_thread(load)

        agent = AskAgent(
            backend=choice.backend,
            model=choice.model,
            retriever=SearchRetriever(self.search, context),
            backend_name=choice.name,
            cloud_consent=cloud_consent,
            consent_remembered=choice.remembered,
            max_meetings=self.settings.ask.max_meetings,
            max_context=self.settings.generation.max_context,
            filters=filters,
            previous=(previous.question, previous.findings()) if previous else None,
            gate=self.gate,
        )
        if progress is not None:
            agent.progress = progress
        return agent

    async def ask(
        self,
        question: str,
        *,
        backend: str | None = None,
        model: str | None = None,
        cloud_consent: bool = False,
        filters: SearchFilters | None = None,
        previous_id: str | None = None,
        save: bool | None = None,
        progress: Callable[[float, str], None] | None = None,
    ) -> tuple[AskResult, AnswerRecord | None]:
        """Answer and (unless ``save`` is false or history is off) save. For the CLI and tests;
        the web page uses :meth:`start`."""
        choice = self.choose(backend, model)
        previous = self._get(previous_id) if previous_id else None
        agent = self._agent(
            choice,
            cloud_consent=cloud_consent,
            filters=filters or SearchFilters(),
            previous=previous,
            progress=progress,
        )
        result = await agent.run(question)
        keep = self.settings.ask.keep_history if save is None else save
        record = await asyncio.to_thread(self.save, result, previous_id) if keep else None
        return result, record

    def running(self) -> LongTask | None:
        task = self.tasks.for_note(TASK_KEY)
        return task if task is not None and task.state is TaskState.RUNNING else None

    def start(
        self,
        question: str,
        *,
        backend: str | None = None,
        model: str | None = None,
        cloud_consent: bool = False,
        filters: SearchFilters | None = None,
        previous_id: str | None = None,
    ) -> LongTask:
        """Start answering in the background. Consent and the choice are checked first, so a
        refused question fails here and nothing is sent."""
        if self.running() is not None:
            raise MM3Error(
                E_ASK_RUNNING,
                "Another question is being answered.",
                "Wait for it to finish, or cancel it.",
                status_code=409,
            )
        choice = self.choose(backend, model)
        enforce_ask_consent(choice.backend, cloud_consent, choice.remembered)
        previous = self._get(previous_id) if previous_id else None
        self.vault_root()

        async def work(task: LongTask) -> AnswerRecord | AskResult:
            agent = self._agent(
                choice,
                cloud_consent=cloud_consent,
                filters=filters or SearchFilters(),
                previous=previous,
                progress=task.update,
            )
            result = await agent.run(question)
            task.update(0.98, "Saving the answer")
            if not self.settings.ask.keep_history:
                return result
            return await asyncio.to_thread(self.save, result, previous_id)

        info = {
            "question": question,
            "backend": choice.name,
            "model": choice.model,
            "local": choice.is_local,
        }
        task = self.tasks.start(TASK_KEY, "ask", work, info)
        task.message = "Planning the searches"
        return task

    def task(self, task_id: str) -> LongTask:
        task = self.tasks.get(task_id)
        if task is None or task.mm3_id != TASK_KEY:
            raise MM3Error(
                "E_TASK_NOT_FOUND",
                "That question is no longer running here.",
                "Ask it again.",
                status_code=404,
            )
        return task

    async def cancel(self, task: LongTask) -> None:
        await self.tasks.cancel(task)

    # -- saving -------------------------------------------------------------------------

    def save(self, result: AskResult, parent_id: str | None = None) -> AnswerRecord:
        root = self.vault_root()
        answer_id = new_answer_id()
        saved: SavedAnswer = write_answer_note(
            root, self.settings.ask.answers_subfolder, result, answer_id, base_url(self.settings)
        )
        record = AnswerRecord(
            id=answer_id,
            question=result.question,
            asked_at=result.started_at,
            backend=result.backend,
            model=result.model,
            vault_path=saved.relative,
            status="done",
            duration_s=round(result.trace.seconds, 1),
            input_tokens=result.trace.input_tokens or None,
            output_tokens=result.trace.output_tokens or None,
            relevant=len(result.rows),
            parent_id=parent_id,
            sources=tuple(
                SourceRef(
                    mm3_id=m.mm3_id,
                    stem=m.stem,
                    title=m.title,
                    date=m.date,
                    note_path=m.note_path,
                    relevance=m.relevance or "yes",
                    finding=m.finding,
                )
                for m in result.relevant
            ),
        )
        return self.store.add(record)

    # -- history ------------------------------------------------------------------------

    def _get(self, answer_id: str) -> AnswerRecord:
        record = self.store.get(answer_id)
        if record is None:
            raise MM3Error(
                E_ASK_NOT_FOUND,
                "That answer is not in the history.",
                "It may have been deleted.",
                status_code=404,
            )
        return record

    def locate(self, answer_id: str) -> Located:
        """The answer and its note, re-found by ``mm3-answer-id`` if it was moved in the vault
        (the history then follows it)."""
        record = self._get(answer_id)
        root = self.vault_root()
        path = resolve_answer(root, record.vault_path, record.id)
        moved = False
        if path is not None:
            relative = path.relative_to(root).as_posix()
            if relative != record.vault_path:
                self.store.set_path(record.id, relative)
                record = self._get(answer_id)
                moved = True
        return Located(record, path, moved)

    def delete(self, answer_id: str) -> bool:
        """Delete the vault note (if it is still there) and the history row. Returns whether a
        note was deleted."""
        located = self.locate(answer_id)
        removed = False
        if located.path is not None:
            removed = delete_answer_note(self.vault_root(), located.path, answer_id)
        self.store.delete(answer_id)
        return removed

    def forget(self, answer_id: str) -> None:
        """Remove the history row only (the note is gone or the user keeps it)."""
        self._get(answer_id)
        self.store.delete(answer_id)

    def citing(self, mm3_id: str) -> list[AnswerRecord]:
        return self.store.citing(mm3_id)
