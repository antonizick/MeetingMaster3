"""The ``ingest`` stage: probe the stored upload and normalise it to ``audio.wav``."""

from __future__ import annotations

from pathlib import Path

from meetingmaster3.audio.ingest import normalise, probe
from meetingmaster3.errors import MM3Error
from meetingmaster3.jobs.files import WAV_NAME, resolve_in_job
from meetingmaster3.jobs.stage import BaseStage, StageContext


class IngestStage(BaseStage):
    name = "ingest"
    display_name = "Preparing audio"
    uses_gpu = False

    def run(self, ctx: StageContext) -> Path:
        src = resolve_in_job(ctx.job_dir, ctx.job.audio_path)
        if src is None or not src.is_file():
            raise MM3Error(
                "E_AUDIO_MISSING",
                "The uploaded audio for this job is gone.",
                "Delete this job and upload the recording again.",
                status_code=409,
            )
        ctx.check_cancelled()
        ctx.progress(0.05, "Reading the file format")
        info = probe(src)
        ctx.check_cancelled()
        ctx.progress(0.2, f"Converting {info.codec} audio to 16 kHz mono")
        dst = ctx.artifact(WAV_NAME)
        normalise(src, dst, info.duration_seconds)
        ctx.check_cancelled()
        ctx.progress(1.0, f"Audio ready ({info.duration_seconds / 60:.1f} min)")
        return dst
