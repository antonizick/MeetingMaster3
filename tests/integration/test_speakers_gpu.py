"""Voice recognition on the real models (Phase 07 acceptance). Needs the ``ml`` extra, a CUDA GPU
and the downloaded models; skipped in CI by the ``gpu``/``models`` markers.

Run on the reference machine:
    uv run --extra ml pytest -m "gpu and models" tests/integration/test_speakers_gpu.py -s
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from meetingmaster3.audio.ingest import probe
from meetingmaster3.audio.stage import IngestStage
from meetingmaster3.config.settings import Settings
from meetingmaster3.jobs.files import job_dir, new_job_id
from meetingmaster3.jobs.models import JobOptions, JobStatus
from meetingmaster3.jobs.runner import JobRunner
from meetingmaster3.jobs.stage import Stage
from meetingmaster3.speakers.stages import SpeakerConfirmationStage, SpeakerSuggestStage
from meetingmaster3.speakers.store import VoiceprintStore
from meetingmaster3.transcription import models
from meetingmaster3.transcription.stages import AlignStage, DiarizeStage, TranscribeStage

from ..unit.jobs.helpers import Log, RecStage, make_runner, wait_status
from .test_transcription_gpu import FIXTURE, REAL_MODELS_DIR, require_engine

pytestmark = [pytest.mark.gpu, pytest.mark.models]


def overlap(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> float:
    return sum(
        max(0.0, min(x["end"], y["end"]) - max(x["start"], y["start"])) for x in a for y in b
    )


def same_voice_label(first: dict[str, Any], second: dict[str, Any]) -> dict[str, str]:
    """Second-run label → first-run label, by the most overlapping diarization turns (the
    diarizer may number speakers differently between runs)."""

    def turns(info: dict[str, Any], label: str) -> list[dict[str, Any]]:
        return [t for t in info["turns"] if t["speaker"] == label]

    return {
        lbl2: max(
            first["speakers"], key=lambda lbl1: overlap(turns(first, lbl1), turns(second, lbl2))
        )
        for lbl2 in second["speakers"]
    }


async def run_job(runner: JobRunner, title: str) -> tuple[str, Path]:
    job_id = new_job_id()
    folder = job_dir(runner.jobs_root, job_id, create=True)
    shutil.copyfile(FIXTURE, folder / "original.opus")
    runner.create_job(
        job_id,
        options=JobOptions(title=title),
        source_filename=FIXTURE.name,
        audio_name="original.opus",
        duration_seconds=probe(folder / "original.opus").duration_seconds,
    )
    status = await wait_status(
        runner, job_id, JobStatus.WAITING_FOR_INPUT, JobStatus.FAILED, timeout=600
    )
    assert status is JobStatus.WAITING_FOR_INPUT, runner.jobs.get(job_id).error_message
    return job_id, folder


async def test_second_run_suggests_the_enrolled_voices(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, record_property: pytest.RecordProperty
) -> None:
    """Acceptance: enroll both AMI speakers, run the clip again, get correct suggestions above
    the threshold."""
    base = require_engine()
    if not models.diarization_cached(REAL_MODELS_DIR):
        pytest.skip("the diarization model is not downloaded")
    monkeypatch.setenv("MM3_MODELS_DIR", str(REAL_MODELS_DIR))
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")  # everything must load from the cache
    settings = Settings.model_validate(
        {**base.model_dump(), "privacy": {**base.privacy.model_dump(), "voiceprints_enabled": True}}
    )
    stages: list[Stage] = [
        IngestStage(),
        TranscribeStage(),
        AlignStage(),
        DiarizeStage(),
        SpeakerSuggestStage(),
        SpeakerConfirmationStage(),
        RecStage("generate", Log()),
    ]
    runner = make_runner(tmp_path, stages, settings)
    await runner.start(prune=False)
    try:
        first, folder1 = await run_job(runner, "First")
        payload = json.loads((folder1 / "speakers.json").read_text())
        assert payload["model_id"].startswith(f"{models.DIARIZATION_MODEL}/embedding@")
        labels = [s["label"] for s in payload["speakers"]]
        assert len(labels) >= 2
        names = {lbl: f"AMI speaker {i + 1}" for i, lbl in enumerate(labels)}
        for s in payload["speakers"]:
            print(f"\n{s['label']}: talk {s['talk_seconds']} s, embedded "
                  f"{s['embedded_seconds']} s in {s['embedded_segments']} windows")  # fmt: skip
        runner.submit_input(
            first, {"speakers": {lbl: {"name": n, "enroll": True} for lbl, n in names.items()}}
        )
        await wait_status(runner, first, JobStatus.WRITTEN, JobStatus.FAILED, timeout=120)
        assert runner.jobs.get(first).status is JobStatus.WRITTEN
        store = VoiceprintStore(runner.db, enabled=True)
        enrolled = [p for p in store.list_people() if p.n_samples]
        assert len(enrolled) == len(labels)

        second, folder2 = await run_job(runner, "Second")
        payload2 = json.loads((folder2 / "speakers.json").read_text())
        mapping = same_voice_label(
            json.loads((folder1 / "diarization.json").read_text()),
            json.loads((folder2 / "diarization.json").read_text()),
        )
        threshold = settings.speakers.match_threshold
        for s in payload2["speakers"]:
            suggestion = s["suggestion"]
            assert suggestion is not None, s["candidates"]
            assert suggestion["name"] == names[mapping[s["label"]]]
            assert suggestion["score"] >= threshold
            others = [c["score"] for c in s["candidates"] if not c["suggested"]]
            print(f"{s['label']}: suggested {suggestion['name']} at {suggestion['score']}, "
                  f"next best {max(others, default=None)}")  # fmt: skip
            record_property(f"score_{s['label']}", suggestion["score"])
        await runner.cancel(second)
    finally:
        await runner.stop()
