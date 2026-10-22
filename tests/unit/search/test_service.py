"""The search service: the GPU rule, vault-change triggers, delete and the CLI's gate."""

from __future__ import annotations

import asyncio
import sqlite3
import time
from pathlib import Path

import pytest

from meetingmaster3.config.settings import Settings
from meetingmaster3.jobs.models import JobStatus
from meetingmaster3.llm.fake import FakeLLMBackend
from meetingmaster3.search import service as service_module
from meetingmaster3.search.service import JobsTableGate, RunnerGate, SearchService
from meetingmaster3.vault.io import atomic_write_text
from tests.search_corpus import MEETINGS_DIR, by_key, note_text
from tests.unit.jobs.helpers import Log, RecStage, add_job, make_paths, make_runner, wait_status


class TimedFake(FakeLLMBackend):
    """Records when each embedding call happened."""

    def __init__(self) -> None:
        super().__init__(id="ollama", kind="ollama")
        self.times: list[float] = []

    async def embed(self, model, texts, *, purpose="document"):  # type: ignore[no-untyped-def]
        self.times.append(time.monotonic())
        return await super().embed(model, texts, purpose=purpose)


def _service(
    settings: Settings, tmp: Path, fake: FakeLLMBackend, gate: object = None
) -> SearchService:
    return SearchService(settings, make_paths(tmp), lambda: ["ollama"], lambda n: fake, gate)  # type: ignore[arg-type]


async def test_indexing_waits_while_a_job_holds_the_gpu(
    tmp_path: Path, search_settings: Settings
) -> None:
    log = Log()
    gpu_stage = RecStage("transcribe", log, gpu=True, seconds=0.6)
    runner = make_runner(tmp_path / "runner", [RecStage("ingest", log), gpu_stage])
    await runner.start(prune=False)
    fake = TimedFake()
    service = _service(search_settings, tmp_path / "svc", fake, RunnerGate(runner))
    try:
        job = add_job(runner)
        await asyncio.to_thread(gpu_stage.entered.wait, 5)
        assert not runner.gpu_idle()
        await service.update_now()
        await wait_status(runner, job, JobStatus.WRITTEN)
        gpu_end = next(end for name, _, _, end in log.runs if name == "transcribe")
        assert fake.times and min(fake.times) >= gpu_end  # nothing embedded during the GPU stage
    finally:
        await service.stop()
        await runner.stop()


async def test_a_job_arriving_waits_at_most_one_batch(tmp_path: Path) -> None:
    runner = make_runner(tmp_path, [RecStage("transcribe", Log(), gpu=True)])
    await runner.start(prune=False)
    try:
        async with runner.background_gpu(poll_s=0.01):
            assert not runner.gpu_idle()  # a job's GPU stage would wait for this hold
        assert runner.gpu_idle()
    finally:
        await runner.stop()


async def test_a_vault_write_schedules_an_update(
    tmp_path: Path, search_settings: Settings, corpus_vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service_module, "DEBOUNCE_S", 0.01)
    fake = FakeLLMBackend(id="ollama", kind="ollama")
    service = _service(search_settings, tmp_path / "svc", fake)
    await service.start()
    try:
        await _until(lambda: service.last_report is not None)
        assert service.status()["meetings"] == 7
        m = by_key("finance")
        new = corpus_vault / MEETINGS_DIR / "2026-10-01 - Board Prep.md"
        text = note_text(m).replace(str(m.id), "00000000-0000-4000-8000-000000000042")
        await asyncio.to_thread(atomic_write_text, new, text, vault_root=corpus_vault)
        await _until(lambda: service.status()["meetings"] == 8)
        # A write outside the vault (app data) does not trigger anything.
        before = service.task
        atomic_write_text(tmp_path / "elsewhere.md", "x")
        await asyncio.sleep(0.1)
        assert service.task is before
    finally:
        await service.stop()


async def test_delete_index_removes_the_files_and_switches_indexing_off(
    tmp_path: Path, search_settings: Settings
) -> None:
    service = _service(search_settings, tmp_path, FakeLLMBackend(id="ollama", kind="ollama"))
    await service.update_now()
    db = service.paths.search_database
    assert db.exists()
    removed = await service.delete_index()
    assert db in removed and not db.exists()
    assert search_settings.search.enabled is False
    with pytest.raises(Exception, match="switched off"):
        await service.query("budget")
    assert service.status()["exists"] is False


async def test_rebuild_starts_from_scratch(tmp_path: Path, search_settings: Settings) -> None:
    fake = FakeLLMBackend(id="ollama", kind="ollama")
    service = _service(search_settings, tmp_path, fake)
    await service.update_now()
    first = len(fake.embed_calls)
    again = await service.update_now()
    assert again is not None and again.embedded == 0
    rebuilt = await service.update_now(rebuild=True)
    assert rebuilt is not None and rebuilt.added == 14 and rebuilt.embedded > 0
    assert len(fake.embed_calls) > first
    await service.stop()


async def test_a_search_refreshes_a_stale_index(
    tmp_path: Path, search_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _service(search_settings, tmp_path, FakeLLMBackend(id="ollama", kind="ollama"))
    await service.start()
    try:
        await _until(lambda: service.last_report is not None and not service.running())
        asked: list[bool] = []
        monkeypatch.setattr(service, "schedule", lambda **kw: asked.append(True))
        await service.query("budget")
        assert asked == []  # fresh
        monkeypatch.setattr(service_module, "STALE_S", -1.0)
        await service.query("budget")
        assert asked == [True]
    finally:
        await service.stop()


def test_jobs_table_gate_sees_active_jobs(tmp_path: Path) -> None:
    db = tmp_path / "mm3.db"
    assert JobsTableGate(db).busy() is False  # no database yet
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE jobs (id TEXT, status TEXT)")
    conn.execute("INSERT INTO jobs VALUES ('a', 'written')")
    conn.commit()
    assert JobsTableGate(db).busy() is False
    conn.execute("INSERT INTO jobs VALUES ('b', 'running')")
    conn.commit()
    conn.close()
    assert JobsTableGate(db).busy() is True


async def test_status_without_a_vault(tmp_path: Path) -> None:
    settings = Settings()
    settings.search.enabled = True
    service = _service(settings, tmp_path, FakeLLMBackend(id="ollama", kind="ollama"))
    with pytest.raises(Exception, match="no vault"):
        service.start_update()
    status = service.status()
    assert status["exists"] is False and status["embedder"]["badge"] == "local"


async def _until(check: object, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():  # type: ignore[operator]
            return
        await asyncio.sleep(0.02)
    raise AssertionError("timed out")
