"""The transcription stages run through the real JobRunner with a fake engine."""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from typing import Any

import pytest

from meetingmaster3.config.settings import Settings
from meetingmaster3.domain.transcript import Transcript
from meetingmaster3.errors import MM3Error
from meetingmaster3.jobs.files import job_dir, new_job_id
from meetingmaster3.jobs.models import JobOptions, JobStatus, StageStatus
from meetingmaster3.jobs.runner import JobRunner
from meetingmaster3.jobs.stage import BaseStage, Stage, StageContext, UnavailableStage, input_path
from meetingmaster3.transcription import stages as tstages
from meetingmaster3.transcription.stages import (
    AlignStage,
    DiarizeStage,
    TranscribeStage,
    build_stage,
    resolve_plan,
)

from ..jobs.helpers import Log, RecStage, make_runner, wait_status
from .fakes import FakeEngine


class NoopIngest(BaseStage):
    name = "ingest"

    def run(self, ctx: StageContext) -> Path:
        path = ctx.artifact("audio.wav")
        path.write_bytes(b"RIFF")
        return path


def pipeline(engine: FakeEngine, tail: Stage | None = None) -> list[Stage]:
    def factory() -> FakeEngine:
        return engine

    return [
        NoopIngest(),
        TranscribeStage(factory),
        AlignStage(factory),
        DiarizeStage(factory),
        tail or RecStage("speaker_suggest", Log()),
    ]


def runner_for(
    tmp_path: Path, engine: FakeEngine, settings: Settings | None = None, tail: Stage | None = None
) -> JobRunner:
    return make_runner(tmp_path, pipeline(engine, tail), settings)


def add(runner: JobRunner, **options: Any) -> str:
    job_id = new_job_id()
    folder = job_dir(runner.jobs_root, job_id, create=True)
    (folder / "original.wav").write_bytes(b"RIFF")
    runner.create_job(
        job_id,
        options=JobOptions(title="Budget", **options),
        source_filename="budget.wav",
        audio_name="original.wav",
        duration_seconds=10.0,
    )
    return job_id


def final(runner: JobRunner, job_id: str) -> Transcript:
    path = job_dir(runner.jobs_root, job_id) / "transcript.final.json"
    return Transcript.model_validate_json(path.read_text("utf-8"))


def artifact(runner: JobRunner, job_id: str, name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((job_dir(runner.jobs_root, job_id) / name).read_text())
    return data


def token_settings() -> Settings:
    return Settings(secrets={"hf_token": "hf_test_token_value"})  # type: ignore[arg-type]


# -- happy path --------------------------------------------------------------------------------


async def test_full_run_produces_a_diarized_transcript(
    tmp_path: Path, handoff_calls: list[Any]
) -> None:
    engine = FakeEngine()
    runner = runner_for(tmp_path, engine, token_settings())
    await runner.start(prune=False)
    try:
        job_id = add(runner, backend="ollama")
        await wait_status(runner, job_id, JobStatus.WRITTEN)
        t = final(runner, job_id)
        described = runner.describe(job_id)
    finally:
        await runner.stop()
    # vram8 defaults (Phase 05 recommendation), passed to faster-whisper
    asr = engine.kwargs("load_asr")[0]
    assert asr == {
        "model": "large-v3-turbo",
        "device": "cuda",
        "compute_type": "int8_float16",
        "language": None,
        "local_only": False,
    }
    assert engine.kwargs("transcribe")[0] == {"batch_size": 8, "language": "en"}
    assert engine.kwargs("load_diarizer")[0]["token"] == "hf_test_token_value"
    assert handoff_calls == ["ollama"]  # Ollama asked to unload before transcription (R5)
    # one segment held two speakers; it is split at the word-level speaker change
    assert t.diarized and t.language == "en" and t.model == "large-v3-turbo"
    assert [(s.speaker_label, s.text) for s in t.segments] == [
        ("SPEAKER_00", "Shall we look at the budget?"),
        ("SPEAKER_01", "Yes. I think it is fine."),
        ("SPEAKER_00", "Okay, good."),
    ]
    assert t.speaker_labels == ["SPEAKER_00", "SPEAKER_01"]
    assert t.segments[0].words[-1].text == "um" and t.segments[0].words[-1].score is None
    assert artifact(runner, job_id, "transcript.json")["language_probability"] == 0.99
    assert artifact(runner, job_id, "aligned.json")["aligned"] is True
    diar = artifact(runner, job_id, "diarization.json")
    assert diar["status"] == "ok" and set(diar["speakers"]) == {"SPEAKER_00", "SPEAKER_01"}
    assert described["warnings"] == []
    assert {s["stage"]: s["artifact"] for s in described["stages"]}["diarize"] == (
        "transcript.final.json"
    )


async def test_resume_skips_completed_transcription_stages(tmp_path: Path) -> None:
    engine = FakeEngine()
    tail = RecStage("speaker_suggest", Log(), fail=1)
    runner = runner_for(tmp_path, engine, token_settings(), tail)
    await runner.start(prune=False)
    try:
        job_id = add(runner)
        await wait_status(runner, job_id, JobStatus.FAILED)
        runner.resume(job_id)
        await wait_status(runner, job_id, JobStatus.WRITTEN)
    finally:
        await runner.stop()
    assert engine.names().count("transcribe") == 1
    assert engine.names().count("align") == 1
    assert engine.names().count("diarize") == 1


async def test_cancel_during_transcription_stops_at_the_next_chunk(tmp_path: Path) -> None:
    block = threading.Event()
    engine = FakeEngine(block=block)
    runner = runner_for(tmp_path, engine)
    await runner.start(prune=False)
    try:
        job_id = add(runner)
        await wait_status(runner, job_id, JobStatus.RUNNING)
        while "transcribe" not in engine.names():
            await asyncio.sleep(0.01)
        job = await runner.cancel(job_id)
        assert job.status is JobStatus.CANCELLED
        assert runner.stages.get(job_id, "transcribe").status is StageStatus.CANCELLED
    finally:
        block.set()
        await runner.stop()
    assert "align" not in engine.names()


# -- out of memory ----------------------------------------------------------------------------


async def test_oom_is_retried_exactly_once_with_smaller_settings(tmp_path: Path) -> None:
    engine = FakeEngine(oom={"transcribe": 1})
    runner = runner_for(tmp_path, engine, token_settings())
    await runner.start(prune=False)
    try:
        job_id = add(runner)
        await wait_status(runner, job_id, JobStatus.WRITTEN)
        job = runner.jobs.get(job_id)
        rec = runner.stages.get(job_id, "transcribe")
        described = runner.describe(job_id)
    finally:
        await runner.stop()
    assert engine.names().count("transcribe") == 2
    assert [k["batch_size"] for k in engine.kwargs("transcribe")] == [8, 4]
    assert [k["compute_type"] for k in engine.kwargs("load_asr")] == [
        "int8_float16",
        "int8_float16",
    ]
    assert rec.attempt == 2
    assert job.settings["batch_size"] == 4 and job.settings["compute_type"] == "int8_float16"
    assert any("Ran out of GPU memory" in w["message"] for w in described["warnings"])


async def test_second_oom_fails_with_smaller_model_suggestion_then_resume(
    tmp_path: Path,
) -> None:
    engine = FakeEngine(oom={"transcribe": 2})
    runner = runner_for(tmp_path, engine, token_settings())
    await runner.start(prune=False)
    try:
        job_id = add(runner)
        await wait_status(runner, job_id, JobStatus.FAILED)
        job = runner.jobs.get(job_id)
        assert engine.names().count("transcribe") == 2  # one automatic retry, no more
        assert job.error_code == "E_OOM" and "medium" in (job.error_hint or "")
        error = runner.stages.get(job_id, "transcribe").detail["error"]
        assert error["details"]["suggested_overrides"] == {"transcription_model": "medium"}
        # the UI's "Retry with medium" button
        runner.resume(job_id, {"transcription_model": "medium"})
        await wait_status(runner, job_id, JobStatus.WRITTEN)
    finally:
        await runner.stop()
    assert engine.kwargs("load_asr")[-1]["model"] == "medium"
    assert final(runner, job_id).model == "medium"


async def test_align_oom_retries_then_succeeds(tmp_path: Path) -> None:
    engine = FakeEngine(oom={"align": 1})
    runner = runner_for(tmp_path, engine, token_settings())
    await runner.start(prune=False)
    try:
        job_id = add(runner)
        await wait_status(runner, job_id, JobStatus.WRITTEN)
    finally:
        await runner.stop()
    assert engine.names().count("align") == 2
    assert artifact(runner, job_id, "aligned.json")["aligned"] is True


async def test_diarize_oom_twice_falls_back_without_failing(tmp_path: Path) -> None:
    engine = FakeEngine(oom={"diarize": 2})
    runner = runner_for(tmp_path, engine, token_settings())
    await runner.start(prune=False)
    try:
        job_id = add(runner)
        await wait_status(runner, job_id, JobStatus.WRITTEN)
        described = runner.describe(job_id)
    finally:
        await runner.stop()
    assert engine.names().count("diarize") == 2
    assert not final(runner, job_id).diarized
    assert artifact(runner, job_id, "diarization.json")["error"]["code"] == "E_OOM"
    assert any("Speakers were not separated" in w["message"] for w in described["warnings"])


# -- language gate -----------------------------------------------------------------------------


async def test_non_english_pauses_then_proceeds(tmp_path: Path) -> None:
    engine = FakeEngine(language=("de", 0.97))
    runner = runner_for(tmp_path, engine, token_settings())
    await runner.start(prune=False)
    try:
        job_id = add(runner)
        await wait_status(runner, job_id, JobStatus.WAITING_FOR_INPUT)
        question = runner.describe(job_id)["waiting_for"]
        assert question["kind"] == "language" and question["detected"] == "de"
        assert question["language_name"] == "German" and question["choices"] == [
            "proceed",
            "abort",
        ]
        assert "transcribe" not in engine.names()  # nothing transcribed before the answer
        with pytest.raises(MM3Error) as bad:
            runner.submit_input(job_id, {"action": "maybe"})
        assert bad.value.code == "E_INPUT_INVALID" and bad.value.status_code == 422
        runner.submit_input(job_id, {"action": "proceed"})
        await wait_status(runner, job_id, JobStatus.WRITTEN)
        described = runner.describe(job_id)
    finally:
        await runner.stop()
    assert engine.kwargs("transcribe")[0]["language"] == "de"
    assert final(runner, job_id).language == "de"
    assert engine.kwargs("load_aligner")[0]["language"] == "de"
    assert any("German" in w["message"] for w in described["warnings"])


async def test_non_english_answer_can_force_english(tmp_path: Path) -> None:
    engine = FakeEngine(language=("nl", 0.6))
    runner = runner_for(tmp_path, engine, token_settings())
    await runner.start(prune=False)
    try:
        job_id = add(runner)
        await wait_status(runner, job_id, JobStatus.WAITING_FOR_INPUT)
        runner.submit_input(job_id, {"action": "proceed", "language": "EN"})
        await wait_status(runner, job_id, JobStatus.WRITTEN)
    finally:
        await runner.stop()
    assert engine.kwargs("transcribe")[0]["language"] == "en"


async def test_non_english_abort_cancels_and_resume_asks_again(tmp_path: Path) -> None:
    engine = FakeEngine(language=("fr", 0.9))
    runner = runner_for(tmp_path, engine, token_settings())
    await runner.start(prune=False)
    try:
        job_id = add(runner)
        await wait_status(runner, job_id, JobStatus.WAITING_FOR_INPUT)
        runner.submit_input(job_id, {"action": "abort"})
        await wait_status(runner, job_id, JobStatus.CANCELLED)
        assert not input_path(job_dir(runner.jobs_root, job_id), "transcribe").exists()
        runner.resume(job_id)
        await wait_status(runner, job_id, JobStatus.WAITING_FOR_INPUT)
    finally:
        await runner.stop()
    assert "transcribe" not in engine.names()


@pytest.mark.parametrize(
    ("policy", "status"), [("abort", JobStatus.FAILED), ("proceed", JobStatus.WRITTEN)]
)
async def test_non_english_policy_option(tmp_path: Path, policy: str, status: JobStatus) -> None:
    engine = FakeEngine(language=("es", 0.95))
    runner = runner_for(tmp_path, engine, token_settings())
    await runner.start(prune=False)
    try:
        job_id = add(runner, on_non_english=policy)
        await wait_status(runner, job_id, status)
        job = runner.jobs.get(job_id)
    finally:
        await runner.stop()
    if policy == "abort":
        assert job.error_code == "E_NOT_ENGLISH"
    else:
        assert engine.kwargs("transcribe")[0]["language"] == "es"


async def test_forced_language_skips_detection(tmp_path: Path) -> None:
    engine = FakeEngine(language=("de", 0.99))
    runner = runner_for(tmp_path, engine, token_settings())
    await runner.start(prune=False)
    try:
        job_id = add(runner, language="en")
        await wait_status(runner, job_id, JobStatus.WRITTEN)
    finally:
        await runner.stop()
    assert "detect_language" not in engine.names()
    assert engine.kwargs("load_asr")[0]["language"] == "en"


# -- alignment and diarization fallbacks -------------------------------------------------------


async def test_alignment_failure_keeps_segment_timestamps(tmp_path: Path) -> None:
    engine = FakeEngine(
        errors={"load_aligner": ValueError("No default align-model for language: xx")}
    )
    runner = runner_for(tmp_path, engine, token_settings())
    await runner.start(prune=False)
    try:
        job_id = add(runner)
        await wait_status(runner, job_id, JobStatus.WRITTEN)
        described = runner.describe(job_id)
    finally:
        await runner.stop()
    assert artifact(runner, job_id, "aligned.json")["aligned"] is False
    assert any(
        "Word-level timestamps are unavailable" in w["message"] for w in described["warnings"]
    )
    t = final(runner, job_id)
    assert [s.start for s in t.segments] == [0.5, 4.5]  # segment-level, not split by word
    assert t.diarized and all(not s.words for s in t.segments)


async def test_no_token_gives_a_non_diarized_transcript_with_a_warning(tmp_path: Path) -> None:
    engine = FakeEngine()
    runner = runner_for(tmp_path, engine, Settings())
    await runner.start(prune=False)
    try:
        job_id = add(runner)
        await wait_status(runner, job_id, JobStatus.WRITTEN)
        described = runner.describe(job_id)
    finally:
        await runner.stop()
    assert "load_diarizer" not in engine.names()
    t = final(runner, job_id)
    assert not t.diarized and t.speaker_labels == []
    assert all(s.speaker_label is None for s in t.segments)
    diar = artifact(runner, job_id, "diarization.json")
    assert diar["status"] == "skipped" and diar["error"]["code"] == "E_HF_TOKEN_MISSING"
    [warning] = described["warnings"]
    assert warning["stage"] == "diarize"
    assert "huggingface.co/pyannote/speaker-diarization-community-1" in warning["message"]


async def test_gated_model_error_falls_back_with_guidance(tmp_path: Path) -> None:
    engine = FakeEngine(errors={"load_diarizer": RuntimeError("403 Client Error: GatedRepoError")})
    runner = runner_for(tmp_path, engine, token_settings())
    await runner.start(prune=False)
    try:
        job_id = add(runner)
        await wait_status(runner, job_id, JobStatus.WRITTEN)
    finally:
        await runner.stop()
    assert not final(runner, job_id).diarized
    diar = artifact(runner, job_id, "diarization.json")
    assert diar["status"] == "failed" and diar["error"]["code"] == "E_HF_ACCESS"


async def test_diarization_disabled_by_option(tmp_path: Path) -> None:
    engine = FakeEngine()
    runner = runner_for(tmp_path, engine, token_settings())
    await runner.start(prune=False)
    try:
        job_id = add(runner, diarize=False)
        await wait_status(runner, job_id, JobStatus.WRITTEN)
        described = runner.describe(job_id)
    finally:
        await runner.stop()
    assert "load_diarizer" not in engine.names()
    assert artifact(runner, job_id, "diarization.json")["status"] == "disabled"
    assert not final(runner, job_id).diarized
    assert any("turned off" in w["message"] for w in described["warnings"])


async def test_speaker_hints_are_passed_and_inverted_hints_ignored(tmp_path: Path) -> None:
    engine = FakeEngine()
    runner = runner_for(tmp_path, engine, token_settings())
    await runner.start(prune=False)
    try:
        good = add(runner, min_speakers=2, max_speakers=3)
        await wait_status(runner, good, JobStatus.WRITTEN)
        bad = add(runner, min_speakers=4, max_speakers=2)
        await wait_status(runner, bad, JobStatus.WRITTEN)
        described = runner.describe(bad)
    finally:
        await runner.stop()
    assert engine.kwargs("diarize") == [
        {"min_speakers": 2, "max_speakers": 3},
        {"min_speakers": None, "max_speakers": None},
    ]
    assert any("Ignoring the speaker hints" in w["message"] for w in described["warnings"])


async def test_no_speech_produces_an_empty_transcript(tmp_path: Path) -> None:
    class Silent(FakeEngine):
        def transcribe(self, asr: Any, audio: Any, **kw: Any) -> dict[str, Any]:
            self._call("transcribe")
            return {"segments": [], "language": "en"}

    engine = Silent()
    runner = runner_for(tmp_path, engine, token_settings())
    await runner.start(prune=False)
    try:
        job_id = add(runner)
        await wait_status(runner, job_id, JobStatus.WRITTEN)
    finally:
        await runner.stop()
    assert final(runner, job_id).segments == []
    assert "load_aligner" not in engine.names() and "load_diarizer" not in engine.names()


async def test_cpu_device_uses_int8(tmp_path: Path, handoff_calls: list[Any]) -> None:
    engine = FakeEngine(cuda=False)
    runner = runner_for(tmp_path, engine, token_settings())
    await runner.start(prune=False)
    try:
        job_id = add(runner)
        await wait_status(runner, job_id, JobStatus.WRITTEN)
    finally:
        await runner.stop()
    asr = engine.kwargs("load_asr")[0]
    assert asr["device"] == "cpu" and asr["compute_type"] == "int8" and asr["model"] == "small"
    assert handoff_calls == []  # no GPU, so no reason to evict Ollama


# -- plan and registration ---------------------------------------------------------------------


def test_resolve_plan_precedence() -> None:
    s = Settings()
    assert resolve_plan(s, {}, cuda=True).model == "large-v3-turbo"
    s = Settings(transcription={"model": "medium", "batch_size": 2, "compute_type": "float16"})  # type: ignore[arg-type]
    plan = resolve_plan(s, {}, cuda=True)
    assert (plan.model, plan.batch_size, plan.compute_type) == ("medium", 2, "float16")
    plan = resolve_plan(
        s, {"transcription_model": "small", "batch_size": 1, "compute_type": "int8"}, cuda=True
    )
    assert (plan.model, plan.batch_size, plan.compute_type) == ("small", 1, "int8")
    forced_cpu = Settings(transcription={"device": "cpu"})  # type: ignore[arg-type]
    plan = resolve_plan(forced_cpu, {"compute_type": "int8_float16"}, cuda=True)
    assert plan.device == "cpu" and plan.compute_type == "int8"
    cuda_wanted = Settings(transcription={"device": "cuda"})  # type: ignore[arg-type]
    assert resolve_plan(cuda_wanted, {}, cuda=False).device == "cpu"


def test_build_stage_without_engine_is_a_clear_placeholder(monkeypatch: pytest.MonkeyPatch) -> None:
    from meetingmaster3.transcription import models

    monkeypatch.setattr(models, "missing_engine_modules", lambda *a: ["torch", "whisperx"])
    stage = build_stage("transcribe", "Transcribing", Settings())
    assert isinstance(stage, UnavailableStage) and stage.uses_gpu
    assert stage.message is not None and "Transcription engine not installed" in stage.message
    assert "uv sync --extra ml" in stage.hint

    monkeypatch.setattr(models, "missing_engine_modules", lambda *a: [])
    assert isinstance(build_stage("align", "Aligning", Settings()), AlignStage)
    assert isinstance(build_stage("diarize", "Diarizing", Settings()), DiarizeStage)


def test_pipeline_uses_real_stages_when_the_engine_is_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from meetingmaster3.jobs.pipeline import build_pipeline
    from meetingmaster3.transcription import models

    monkeypatch.setattr(models, "missing_engine_modules", lambda *a: [])
    p = build_pipeline("meeting", Settings(), fake=False)
    assert isinstance(p.stage("transcribe"), TranscribeStage)
    assert [p.stage(n).uses_gpu for n in ("transcribe", "align", "diarize")] == [True] * 3


def test_validate_input_normalises() -> None:
    stage = TranscribeStage(FakeEngine)
    assert stage.validate_input({"action": "proceed", "language": "DE"}) == {
        "action": "proceed",
        "language": "de",
    }
    assert stage.validate_input({"action": "abort"}) == {"action": "abort"}
    for bad in (
        {},
        {"action": "proceed", "language": "../x"},
        {"action": "proceed", "language": 3},
    ):
        with pytest.raises(MM3Error):
            stage.validate_input(bad)


def test_oom_error_without_smaller_model() -> None:
    plan = tstages.TranscriptionPlan("tiny", "cuda", "int8_float16", 1, (1.0, 2.0))
    err = tstages.oom_error("transcription", plan, 2)
    assert err.code == "E_OOM" and "suggested_overrides" not in err.details
    assert "Close other programs" in err.hint
