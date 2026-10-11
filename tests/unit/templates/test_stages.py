"""The generate and write stages through the real JobRunner, with a fake transcript and the
FakeLLMBackend, writing into a temporary vault."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from meetingmaster3.config.settings import BackendConfig, Settings
from meetingmaster3.jobs.files import job_dir
from meetingmaster3.jobs.models import JobStatus
from meetingmaster3.jobs.runner import JobRunner
from meetingmaster3.jobs.stage import CancelToken, StageContext
from meetingmaster3.llm.base import GenerateRequest, LLMBackend
from meetingmaster3.llm.fake import FakeLLMBackend
from meetingmaster3.markdown.note_parser import parse_note
from meetingmaster3.markdown.transcript_format import parse_transcript
from meetingmaster3.speakers.stages import SpeakerConfirmationStage
from meetingmaster3.storage.repositories import RecentMeetingsRepository
from meetingmaster3.templates.stages import GenerateStage, WriteStage
from tests.unit.jobs.helpers import Log, RecStage, add_job, make_runner, wait_status

SPEAKERS = {"speakers": {"SPEAKER_00": "Alice Chen", "SPEAKER_01": "Bob Okafor"}}


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    (root / ".obsidian").mkdir(parents=True)
    return root.resolve()


def settings_for(vault: Path | None, **generation: Any) -> Settings:
    s = Settings()
    s.vault.path = vault
    for k, v in generation.items():
        setattr(s.generation, k, v)
    s.llm.backends["openrouter"] = BackendConfig(kind="openrouter", api_key="sk-test")
    return s


class Backends:
    """A backend factory that records the backends it hands out."""

    def __init__(self, **kw: Any) -> None:
        self.kw = kw
        self.made: list[FakeLLMBackend] = []

    def __call__(self, settings: Settings, name: str | None) -> tuple[str, LLMBackend]:
        name = name or settings.llm.default_backend
        backend = FakeLLMBackend(id=name, is_local=name != "openrouter", **self.kw)
        self.made.append(backend)
        return name, backend


def pipeline(log: Log, backends: Backends) -> list[Any]:
    gen = GenerateStage(None, backends)
    gen.default_model = "fake-model"
    return [
        RecStage("ingest", log),
        RecStage("diarize", log, transcript=True),
        SpeakerConfirmationStage(),
        gen,
        WriteStage(),
    ]


async def run_job(
    runner: JobRunner, job_id: str, *answers: dict[str, Any], final: JobStatus = JobStatus.WRITTEN
) -> dict[str, Any]:
    for answer in answers:
        await wait_status(runner, job_id, JobStatus.WAITING_FOR_INPUT)
        runner.submit_input(job_id, answer)
    await wait_status(runner, job_id, final)
    return runner.describe(job_id)


def written(runner: JobRunner, job_id: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(
        (job_dir(runner.jobs_root, job_id) / "written.json").read_text("utf-8")
    )
    return data


async def test_audio_to_vault_note_and_companion(tmp_path: Path, vault: Path) -> None:
    backends = Backends()
    runner = make_runner(tmp_path, pipeline(Log(), backends), settings_for(vault))
    await runner.start(prune=False)
    try:
        job_id = add_job(runner, title="Product Sync")
        await run_job(runner, job_id, SPEAKERS)
        out = written(runner, job_id)
        note_path, transcript_path = Path(out["note_path"]), Path(out["transcript_path"])
        assert note_path.parent.parent == vault / "Meetings"  # Meetings/{yyyy}/
        assert note_path.name.endswith(" - Product Sync.md")
        assert out["note_relative"] == note_path.relative_to(vault).as_posix()

        parsed = parse_note(note_path.read_text("utf-8"))
        assert parsed.ok and parsed.warnings == ()
        meta = parsed.note.meta
        assert meta.template_id == "executive-summary" and meta.model == "fake-model"
        assert meta.backend == "ollama" and meta.generated_at is not None
        assert meta.participants == ["Alice Chen", "Bob Okafor"]
        assert meta.speakers.names == {"SPEAKER_00": "Alice Chen", "SPEAKER_01": "Bob Okafor"}
        assert meta.tags == ["meeting"]
        assert meta.transcript_ref == transcript_path.name.removesuffix(".md")
        assert [s.id for s in parsed.note.sections][-1] == "ai-recommendations"
        assert "Simulated summary" in parsed.note.sections[0].body_markdown

        companion = parse_transcript(transcript_path.read_text("utf-8"))
        assert companion.doc.meeting_id == meta.id
        assert companion.doc.note_ref == note_path.stem
        assert companion.doc.speakers.names == meta.speakers.names
        assert companion.body_matches_data

        recent = RecentMeetingsRepository(runner.db).get(str(note_path))
        assert recent.mm3_id == str(meta.id) and recent.title == "Product Sync"
        folder = job_dir(runner.jobs_root, job_id)
        assert (folder / "notes.draft.md").is_file() and not (
            folder / "generate.partial.json"
        ).exists()
        gen = json.loads((folder / "generation.json").read_text("utf-8"))
        assert gen["mode"] == "full" and gen["template"] == "executive-summary"
    finally:
        await runner.stop()


async def test_job_options_reach_the_note(tmp_path: Path, vault: Path) -> None:
    runner = make_runner(tmp_path, pipeline(Log(), Backends()), settings_for(vault))
    await runner.start(prune=False)
    try:
        job_id = add_job(runner, title="Retro")
        runner.update_options(
            job_id,
            {
                "template": "decision-log",
                "meeting_date": "2026-10-09",
                "meeting_time": "14:30",
                "tags": ["team"],
                "participants": ["Cara"],
                "location": "Zoom",
                "instructions": "Be terse.",
            },
        )
        await run_job(runner, job_id, SPEAKERS)
        note_path = Path(written(runner, job_id)["note_path"])
        assert note_path.name == "2026-10-09 - Retro.md"
        text = note_path.read_text("utf-8")
        assert "- **Date & Time:** 2026-10-09 14:30" in text
        assert "- **Location / Context:** Zoom" in text
        meta = parse_note(text).note.meta
        assert meta.template_id == "decision-log" and meta.tags == ["meeting", "team"]
        assert meta.participants == ["Alice Chen", "Bob Okafor", "Cara"]
    finally:
        await runner.stop()


async def test_cloud_backend_pauses_for_consent(tmp_path: Path, vault: Path) -> None:
    backends = Backends()
    runner = make_runner(tmp_path, pipeline(Log(), backends), settings_for(vault))
    await runner.start(prune=False)
    try:
        job_id = add_job(runner)
        runner.update_options(job_id, {"backend": "openrouter"})
        await wait_status(runner, job_id, JobStatus.WAITING_FOR_INPUT)
        runner.submit_input(job_id, SPEAKERS)
        await wait_status(runner, job_id, JobStatus.WAITING_FOR_INPUT)
        question = runner.describe(job_id)["waiting_for"]
        assert question["kind"] == "cloud_consent" and question["backend"] == "openrouter"
        assert question["backend_kind"] == "fake" and question["badge"] == "cloud: fake"
        assert question["stage"] == "generate"
        assert all(not b.calls for b in backends.made)  # nothing was sent yet
        runner.submit_input(job_id, {"consent": True})
        await wait_status(runner, job_id, JobStatus.WRITTEN)
        assert runner.get(job_id).settings["cloud_consent_for"] == "openrouter"
        assert any(b.calls for b in backends.made)
    finally:
        await runner.stop()


async def test_declined_consent_fails_without_sending(tmp_path: Path, vault: Path) -> None:
    backends = Backends()
    runner = make_runner(tmp_path, pipeline(Log(), backends), settings_for(vault))
    await runner.start(prune=False)
    try:
        job_id = add_job(runner)
        runner.update_options(job_id, {"backend": "openrouter"})
        job = await run_job(runner, job_id, SPEAKERS, {"consent": False}, final=JobStatus.FAILED)
        assert job["error"]["code"] == "E_CONSENT_REQUIRED"
        assert all(not b.calls for b in backends.made)
        with pytest.raises(Exception, match="not waiting"):
            runner.submit_input(job_id, {"consent": True})  # too late: the job failed
        # Resuming with a local backend then works.
        runner.resume(job_id, {"backend": "ollama"})
        await wait_status(runner, job_id, JobStatus.WRITTEN)
    finally:
        await runner.stop()


async def test_upload_consent_option_skips_the_question(tmp_path: Path, vault: Path) -> None:
    runner = make_runner(tmp_path, pipeline(Log(), Backends()), settings_for(vault))
    await runner.start(prune=False)
    try:
        job_id = add_job(runner)
        runner.update_options(job_id, {"backend": "openrouter", "cloud_consent": True})
        await run_job(runner, job_id, SPEAKERS)
    finally:
        await runner.stop()


async def test_companion_can_be_turned_off(tmp_path: Path, vault: Path) -> None:
    runner = make_runner(
        tmp_path, pipeline(Log(), Backends()), settings_for(vault, write_companion=False)
    )
    await runner.start(prune=False)
    try:
        job_id = add_job(runner)
        job = await run_job(runner, job_id, SPEAKERS)
        out = written(runner, job_id)
        assert out["transcript_path"] is None
        assert not list(vault.rglob("*.transcript.md"))
        meta = parse_note(Path(out["note_path"]).read_text("utf-8")).note.meta
        assert meta.transcript_ref is None
        assert any("companion transcript is turned off" in w["message"] for w in job["warnings"])
    finally:
        await runner.stop()


async def test_missing_vault_fails_then_resumes(tmp_path: Path, vault: Path) -> None:
    settings = settings_for(None)
    runner = make_runner(tmp_path, pipeline(Log(), Backends()), settings)
    await runner.start(prune=False)
    try:
        job_id = add_job(runner)
        job = await run_job(runner, job_id, SPEAKERS, final=JobStatus.FAILED)
        assert job["error"]["code"] == "vault_not_configured"
        assert job["current_stage"] == "write"
        settings.vault.path = vault
        runner.resume(job_id)
        await wait_status(runner, job_id, JobStatus.WRITTEN)
        assert len(list(vault.rglob("*.md"))) >= 2
    finally:
        await runner.stop()


async def test_failed_generation_resumes_from_finished_sections(
    tmp_path: Path, vault: Path
) -> None:
    calls = {"n": 0}

    def flaky(req: GenerateRequest) -> str:
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("model crashed")
        return f"Body {calls['n']}."

    backends = Backends(responder=flaky)
    runner = make_runner(tmp_path, pipeline(Log(), backends), settings_for(vault))
    await runner.start(prune=False)
    try:
        job_id = add_job(runner)
        await run_job(runner, job_id, SPEAKERS, final=JobStatus.FAILED)
        folder = job_dir(runner.jobs_root, job_id)
        partial = json.loads((folder / "generate.partial.json").read_text("utf-8"))
        assert list(partial["sections"]) == ["summary", "decisions"]
        runner.resume(job_id)
        await wait_status(runner, job_id, JobStatus.WRITTEN)
        gen = json.loads((folder / "generation.json").read_text("utf-8"))
        assert gen["reused_sections"] == ["decisions", "summary"]
        sections = parse_note(Path(written(runner, job_id)["note_path"]).read_text("utf-8"))
        bodies = [s.body_markdown for s in sections.note.sections]
        assert bodies[:2] == ["Body 1.", "Body 2."]
    finally:
        await runner.stop()


async def test_regenerate_with_another_template_via_resume(tmp_path: Path, vault: Path) -> None:
    runner = make_runner(tmp_path, pipeline(Log(), Backends()), settings_for(None))
    await runner.start(prune=False)
    try:
        job_id = add_job(runner)
        await run_job(runner, job_id, SPEAKERS, final=JobStatus.FAILED)  # no vault: write fails
        runner.settings.vault.path = vault
        runner.resume(job_id, {"template": "just-the-facts"}, from_stage="generate")
        await wait_status(runner, job_id, JobStatus.WRITTEN)
        meta = parse_note(Path(written(runner, job_id)["note_path"]).read_text("utf-8")).note.meta
        assert meta.template_id == "just-the-facts"
    finally:
        await runner.stop()


async def test_write_is_idempotent_after_a_crash(tmp_path: Path, vault: Path) -> None:
    runner = make_runner(tmp_path, pipeline(Log(), Backends()), settings_for(vault))
    await runner.start(prune=False)
    try:
        job_id = add_job(runner)
        await run_job(runner, job_id, SPEAKERS)
        folder = job_dir(runner.jobs_root, job_id)
        before = sorted(p.name for p in vault.rglob("*.md"))
        ctx = StageContext(
            job=runner.get(job_id),
            stage="write",
            job_dir=folder,
            settings=runner.settings,
            options=dict(runner.get(job_id).settings),
            artifacts={
                "generate": folder / "notes.draft.md",
                "diarize": folder / "transcript.final.json",
            },
            attempt=1,
            token=CancelToken(),
            _progress=lambda *a: None,
            db=runner.db,
        )
        (folder / "written.json").unlink()
        WriteStage().run(ctx)  # a second run (e.g. after a crash before written.json)
        assert sorted(p.name for p in vault.rglob("*.md")) == before  # no "(2)" copies
    finally:
        await runner.stop()


def test_gpu_use_follows_the_jobs_backend() -> None:
    settings = settings_for(None)
    stage = GenerateStage(settings)
    assert stage.uses_gpu and stage.gpu_for({}) and stage.gpu_for({"backend": "ollama"})
    assert not stage.gpu_for({"backend": "openrouter"})
    assert not stage.gpu_for({"backend": "nope"})  # unknown backends fail later, not here


def test_consent_answer_validation() -> None:
    stage = GenerateStage(None)
    assert stage.validate_input({"consent": True}) == {"consent": True}
    with pytest.raises(Exception, match="consent"):
        stage.validate_input({"consent": "yes"})


async def test_missing_model_is_a_clear_error(tmp_path: Path, vault: Path) -> None:
    backends = Backends()
    stages = pipeline(Log(), backends)
    stages[3].default_model = None
    runner = make_runner(tmp_path, stages, settings_for(vault))
    await runner.start(prune=False)
    try:
        job_id = add_job(runner)
        job = await run_job(runner, job_id, SPEAKERS, final=JobStatus.FAILED)
        assert job["error"]["code"] == "E_LLM_CONFIG"
        assert "default_model" in job["error"]["hint"]
    finally:
        await runner.stop()
