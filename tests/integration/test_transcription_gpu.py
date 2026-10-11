"""Real WhisperX on the GPU (Phase 06 acceptance). Needs the ``ml`` extra, a CUDA GPU and the
downloaded models (`mm3 models download`); skipped in CI by the ``gpu``/``models`` markers.

Run on the reference machine:
    uv run --extra ml pytest -m "gpu and models" tests/integration -s
    MM3_PRIVATE_TEST_AUDIO=/path/to/recordings uv run --extra ml pytest -m slow tests/integration -s
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

import pytest

from meetingmaster3.audio.ingest import probe
from meetingmaster3.audio.stage import IngestStage
from meetingmaster3.config.paths import resolve_paths
from meetingmaster3.config.settings import Settings, load_settings
from meetingmaster3.domain.transcript import Transcript
from meetingmaster3.jobs.files import job_dir, new_job_id
from meetingmaster3.jobs.models import JobOptions, JobStatus
from meetingmaster3.jobs.runner import JobRunner
from meetingmaster3.jobs.stage import Stage
from meetingmaster3.transcription import models
from meetingmaster3.transcription.stages import AlignStage, DiarizeStage, TranscribeStage

from ..unit.jobs.helpers import Log, RecStage, make_runner, wait_status

pytestmark = [pytest.mark.gpu, pytest.mark.models]

FIXTURE = Path(__file__).parents[1] / "fixtures" / "audio" / "ami-es2002a-two-speakers.fixture.opus"
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav", ".flac", ".ogg", ".opus", ".webm", ".mp4", ".aac"}

# Captured at import (collection), before the autouse fixture isolates XDG dirs and env vars:
# these tests use the real model cache and the real config (for the Hugging Face token).
REAL_MODELS_DIR = resolve_paths().models_dir
try:
    REAL_SETTINGS: Settings | None = load_settings()
except Exception:  # pragma: no cover - unreadable config
    REAL_SETTINGS = None
PRIVATE_AUDIO = os.environ.get("MM3_PRIVATE_TEST_AUDIO", "")
OFFLINE = os.environ.get("HF_HUB_OFFLINE", "")  # run with HF_HUB_OFFLINE=1 to test offline mode


def require_engine() -> Settings:
    if models.missing_engine_modules():
        pytest.skip("the ml extra is not installed")
    import torch

    if not torch.cuda.is_available():
        pytest.skip("no CUDA GPU")
    if not models.whisper_cached(REAL_MODELS_DIR, "large-v3-turbo"):
        pytest.skip("large-v3-turbo is not downloaded (mm3 models download)")
    return REAL_SETTINGS or Settings()


def transcription_runner(tmp_path: Path, settings: Settings) -> JobRunner:
    stages: list[Stage] = [
        IngestStage(),
        TranscribeStage(),
        AlignStage(),
        DiarizeStage(),
        RecStage("speaker_suggest", Log()),
    ]
    return make_runner(tmp_path, stages, settings)


async def transcribe_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, audio: Path, timeout: float
) -> tuple[Transcript, float, float, JobRunner, str]:
    settings = require_engine()
    monkeypatch.setenv("MM3_MODELS_DIR", str(REAL_MODELS_DIR))
    if OFFLINE:
        monkeypatch.setenv("HF_HUB_OFFLINE", OFFLINE)
    runner = transcription_runner(tmp_path, settings)
    job_id = new_job_id()
    folder = job_dir(runner.jobs_root, job_id, create=True)
    shutil.copyfile(audio, folder / f"original{audio.suffix}")
    duration = probe(folder / f"original{audio.suffix}").duration_seconds
    await runner.start(prune=False)
    try:
        start = time.monotonic()
        runner.create_job(
            job_id,
            options=JobOptions(title="GPU test"),
            source_filename=audio.name,
            audio_name=f"original{audio.suffix}",
            duration_seconds=duration,
        )
        await wait_status(runner, job_id, JobStatus.WRITTEN, JobStatus.FAILED, timeout=timeout)
        elapsed = time.monotonic() - start
        job = runner.jobs.get(job_id)
        assert job.status is JobStatus.WRITTEN, (job.error_code, job.error_message)
    finally:
        await runner.stop()
    final = folder / "transcript.final.json"
    return (
        Transcript.model_validate_json(final.read_text("utf-8")),
        duration,
        elapsed,
        runner,
        job_id,
    )


def stage_seconds(runner: JobRunner, job_id: str) -> dict[str, float]:
    out = {}
    for rec in runner.stages.for_job(job_id):
        if rec.started_at and rec.finished_at:
            out[rec.stage] = round((rec.finished_at - rec.started_at).total_seconds(), 1)
    return out


async def test_fixture_end_to_end_with_diarization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, record_property: pytest.RecordProperty
) -> None:
    """Acceptance: the AMI fixture on the 8 GB GPU with vram8 defaults, diarized, no OOM."""
    t, duration, elapsed, runner, job_id = await transcribe_file(
        tmp_path, monkeypatch, FIXTURE, timeout=600
    )
    rtf = duration / elapsed
    record_property("rtf", round(rtf, 2))
    print(f"\nfixture: {duration:.0f} s audio in {elapsed:.1f} s, RTF {rtf:.1f}x "
          f"(incl. model loading), stages {stage_seconds(runner, job_id)}")  # fmt: skip
    assert runner.stages.get(job_id, "transcribe").attempt == 1  # no OOM retry needed
    assert t.model == "large-v3-turbo" and t.language == "en"
    no_token = REAL_SETTINGS is None or models.hf_token(REAL_SETTINGS) is None
    if no_token and not models.diarization_cached(REAL_MODELS_DIR):
        pytest.skip("no Hugging Face token and no cached diarization model")
    assert t.diarized and len(t.speaker_labels) >= 2
    text = " ".join(s.text for s in t.segments).lower()
    assert "price" in text and "retail" in text
    assert any(s.words for s in t.segments)  # word-level alignment happened


@pytest.mark.slow
async def test_private_recordings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, record_property: pytest.RecordProperty
) -> None:
    """Long real recordings (never committed): MM3_PRIVATE_TEST_AUDIO is a file or a folder."""
    if not PRIVATE_AUDIO:
        pytest.skip("MM3_PRIVATE_TEST_AUDIO is not set")
    root = Path(PRIVATE_AUDIO).expanduser()
    files = (
        [root]
        if root.is_file()
        else sorted(p for p in root.iterdir() if p.suffix.lower() in AUDIO_EXTENSIONS)
    )
    if not files:
        pytest.skip(f"no audio in {root}")
    for i, audio in enumerate(files):
        t, duration, elapsed, runner, job_id = await transcribe_file(
            tmp_path / str(i), monkeypatch, audio, timeout=duration_budget(audio)
        )
        rtf = duration / elapsed
        record_property(f"rtf_{i}", round(rtf, 2))
        # Report only numbers, never names or transcript text (private recordings).
        stages = stage_seconds(runner, job_id)
        print(f"\nrecording {i}: {duration / 60:.1f} min in {elapsed:.0f} s, RTF {rtf:.1f}x, "
              f"{len(t.speaker_labels)} speakers, stages {stages}")  # fmt: skip
        assert t.segments and t.language


def duration_budget(audio: Path) -> float:
    return max(600.0, probe(audio).duration_seconds)  # never slower than real time
