"""Test stages and helpers for the job runner."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from meetingmaster3.config.paths import AppPaths
from meetingmaster3.config.settings import Settings
from meetingmaster3.jobs.fakes import fake_transcript
from meetingmaster3.jobs.files import job_dir, new_job_id
from meetingmaster3.jobs.models import JobOptions, JobStatus
from meetingmaster3.jobs.pipeline import Pipeline
from meetingmaster3.jobs.runner import JobRunner
from meetingmaster3.jobs.stage import BaseStage, Stage, StageContext
from meetingmaster3.speakers.stages import SpeakerConfirmationStage
from meetingmaster3.storage.db import Database

requires_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not installed",
)


def make_tone(path: Path, seconds: float = 2.0, channels: int = 2) -> Path:
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    args = f"-nostdin -loglevel error -y -f lavfi -i sine=frequency=440:duration={seconds}"
    subprocess.run(  # noqa: S603
        [ffmpeg, *args.split(), "-ac", str(channels), str(path)], check=True
    )
    return path


@dataclass
class Log:
    """Shared record of stage runs: (stage, job, start, end)."""

    runs: list[tuple[str, str, float, float]] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def add(self, stage: str, job: str, start: float, end: float) -> None:
        with self.lock:
            self.runs.append((stage, job, start, end))

    def names(self, job: str | None = None) -> list[str]:
        return [r[0] for r in self.runs if job is None or r[1] == job]


class RecStage(BaseStage):
    """Sleeps ``seconds`` cancellably, logs the run and writes ``<name>.json``.

    ``fail`` = number of initial attempts that raise; ``block`` = an event the stage waits on;
    ``transcript`` = write the fake pipeline's diarized transcript instead (a ``diarize`` stand-in
    that the real speaker stages can read).
    """

    def __init__(
        self,
        name: str,
        log: Log,
        *,
        gpu: bool = False,
        seconds: float = 0.0,
        fail: int = 0,
        retries: int = 0,
        block: threading.Event | None = None,
        transcript: bool = False,
    ) -> None:
        self.name, self.uses_gpu, self.transcript = name, gpu, transcript
        super().__init__()
        self.log, self.seconds, self.fail, self.retries, self.block = (
            log,
            seconds,
            fail,
            retries,
            block,
        )
        self.calls = 0
        self.entered = threading.Event()

    def run(self, ctx: StageContext) -> Path:
        self.calls += 1
        assert ctx.db is not None
        start = time.monotonic()
        self.entered.set()
        if self.block is not None:
            while not self.block.wait(0.01):
                ctx.check_cancelled()
        if self.seconds:
            steps = 5
            for i in range(steps):
                ctx.sleep(self.seconds / steps)
                ctx.progress((i + 1) / steps, f"step {i + 1}")
        ctx.check_cancelled()
        if self.calls <= self.fail:
            self.log.add(self.name + "!", ctx.job_id, start, time.monotonic())
            raise RuntimeError(f"{self.name} boom {self.calls}")
        self.log.add(self.name, ctx.job_id, start, time.monotonic())
        if self.transcript:
            return ctx.write_json("transcript.final.json", fake_transcript(5.0).model_dump())
        return ctx.write_json(f"{self.name}.json", {"stage": self.name, "opts": ctx.options})

    def should_retry(self, ctx: StageContext, exc: Exception) -> bool:
        if ctx.attempt <= self.retries:
            ctx.options["batch_size"] = 4
            return True
        return False


def factory(stages: list[Stage]):  # type: ignore[no-untyped-def]
    def build(job_type: str, settings: Settings) -> Pipeline:
        return Pipeline(job_type, tuple(stages))

    return build


def standard_stages(log: Log, **gpu_seconds: float) -> list[Stage]:
    """ingest → transcribe(gpu) → diarize(gpu) → confirm(input) → generate → write."""
    s = gpu_seconds.get("seconds", 0.0)
    return [
        RecStage("ingest", log),
        RecStage("transcribe", log, gpu=True, seconds=s),
        RecStage("diarize", log, gpu=True, seconds=s, transcript=True),
        SpeakerConfirmationStage(),
        RecStage("generate", log),
        RecStage("write", log),
    ]


def make_paths(tmp: Path) -> AppPaths:
    paths = AppPaths(config_dir=tmp / "cfg", data_dir=tmp / "data", cache_dir=tmp / "cache")
    paths.ensure()
    return paths


def make_runner(
    tmp: Path, stages: list[Stage], settings: Settings | None = None, db: Database | None = None
) -> JobRunner:
    paths = make_paths(tmp)
    db = db or Database.open(paths.database)
    return JobRunner(db, settings or Settings(), paths, pipeline_factory=factory(stages))


def add_job(runner: JobRunner, title: str = "Test", audio: bytes = b"RIFF") -> str:
    job_id = new_job_id()
    folder = job_dir(runner.jobs_root, job_id, create=True)
    (folder / "original.wav").write_bytes(audio)
    runner.create_job(
        job_id,
        options=JobOptions(title=title),
        source_filename="test.wav",
        audio_name="original.wav",
        duration_seconds=5.0,
    )
    return job_id


async def wait_status(
    runner: JobRunner, job_id: str, *statuses: JobStatus, timeout: float = 10.0
) -> JobStatus:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = runner.jobs.get(job_id).status
        if status in statuses:
            return status
        await asyncio.sleep(0.01)
    raise AssertionError(f"job {job_id} is {runner.jobs.get(job_id).status}, wanted {statuses}")
