from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from meetingmaster3.cli import app
from meetingmaster3.config.paths import resolve_paths
from meetingmaster3.config.settings import Settings
from meetingmaster3.errors import MM3Error
from meetingmaster3.jobs.fakes import fake_transcript
from meetingmaster3.jobs.models import JobStatus
from meetingmaster3.jobs.pipeline import (
    MEETING_STAGES,
    build_pipeline,
    fake_pipeline_enabled,
    register_stage,
    unregister_stage,
)
from meetingmaster3.jobs.stage import BaseStage, Stage, StageContext, UnavailableStage
from meetingmaster3.storage.db import Database
from meetingmaster3.storage.repositories import JobRepository

from .helpers import add_job, make_runner, wait_status

CANONICAL = [
    "ingest", "transcribe", "align", "diarize", "speaker_suggest",
    "await_speaker_confirmation", "generate", "write",
]  # fmt: skip


def test_canonical_order_and_placeholders(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MM3_FAKE_PIPELINE", raising=False)
    assert not fake_pipeline_enabled()
    p = build_pipeline("meeting", Settings())
    assert p.names == CANONICAL == [s[0] for s in MEETING_STAGES]
    assert type(p.stage("generate")).__name__ == "GenerateStage"
    assert type(p.stage("write")).__name__ == "WriteStage"
    assert type(p.stage("speaker_suggest")).__name__ == "SpeakerSuggestStage"
    # The default backend is the local Ollama, which shares the GPU (R5).
    assert p.stage("transcribe").uses_gpu and p.stage("generate").uses_gpu
    assert not p.stage("write").uses_gpu
    assert all(isinstance(s, Stage) for s in p.stages)
    with pytest.raises(KeyError):
        p.stage("nope")
    with pytest.raises(MM3Error):
        build_pipeline("podcast", Settings())


def test_fake_pipeline_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MM3_FAKE_PIPELINE", "1")
    p = build_pipeline("meeting", Settings())
    assert p.names == CANONICAL
    assert type(p.stage("transcribe")).__name__ == "FakeTranscribe"
    assert type(p.stage("ingest")).__name__ == "IngestStage"  # real ffmpeg ingest
    t = fake_transcript(60)
    assert t.speaker_labels == ["SPEAKER_00", "SPEAKER_01"] and t.duration == 60


@pytest.fixture
def no_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    """Behave as if the ``ml`` extra were not installed."""
    from meetingmaster3.transcription import models

    monkeypatch.setattr(models, "missing_engine_modules", lambda *a: ["torch"])


@pytest.mark.usefixtures("no_engine")
def test_register_stage_replaces_placeholder() -> None:
    class Real(BaseStage):
        name, uses_gpu = "transcribe", True

        def run(self, ctx: StageContext) -> Path:
            return ctx.write_json("transcript.json", {})

    register_stage("transcribe", lambda s: Real())
    try:
        assert isinstance(
            build_pipeline("meeting", Settings(), fake=False).stage("transcribe"), Real
        )
    finally:
        unregister_stage("transcribe")
    assert isinstance(
        build_pipeline("meeting", Settings(), fake=False).stage("transcribe"), UnavailableStage
    )


@pytest.mark.usefixtures("no_engine")
async def test_unavailable_stage_fails_with_install_hint(tmp_path: Path) -> None:
    from meetingmaster3.jobs.pipeline import Pipeline

    stages = list(build_pipeline("meeting", Settings(), fake=False).stages)

    class NoopIngest(BaseStage):
        name = "ingest"

        def run(self, ctx: StageContext) -> Path:
            return ctx.write_json("ingest.json", {})

    stages[0] = NoopIngest()
    runner = make_runner(tmp_path, stages)
    runner._pipeline_factory = lambda jt, s: Pipeline(jt, tuple(stages))
    await runner.start(prune=False)
    try:
        job_id = add_job(runner)
        await wait_status(runner, job_id, JobStatus.FAILED)
        job = runner.jobs.get(job_id)
        assert job.error_code == "E_STAGE_UNAVAILABLE" and "MM3_FAKE_PIPELINE" in (
            job.error_hint or ""
        )
    finally:
        await runner.stop()


def test_cli_jobs_list_and_prune() -> None:
    import datetime as dt

    from meetingmaster3.jobs.files import job_dir, new_job_id

    paths = resolve_paths()
    paths.ensure()
    db = Database.open(paths.database)
    jobs = JobRepository(db)
    job_id = new_job_id()
    folder = job_dir(paths.jobs_dir, job_id, create=True)
    (folder / "audio.opus").write_bytes(b"x" * 2048)
    jobs.create(job_id, stages=["a"], title="Old sync", audio_path="audio.opus",
                status=JobStatus.RUNNING)  # fmt: skip
    old = dt.datetime(2020, 1, 1, tzinfo=dt.UTC)
    jobs.set_status(job_id, JobStatus.WRITTEN, written_at=old, audio_expires_at=old)
    db.close()

    cli = CliRunner()
    out = cli.invoke(app, ["jobs", "list"])
    assert out.exit_code == 0 and job_id in out.output and "until 2020-01-01" in out.output
    out = cli.invoke(app, ["jobs", "prune", "--dry-run"])
    assert out.exit_code == 0 and "Would delete audio of 1 job(s)" in out.output
    assert (folder / "audio.opus").exists()
    out = cli.invoke(app, ["jobs", "prune"])
    assert "Deleted audio of 1 job(s)" in out.output and not (folder / "audio.opus").exists()
    out = cli.invoke(app, ["jobs", "list"])
    assert "audio expired" in out.output
