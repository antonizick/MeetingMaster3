"""Fake stages that sleep, report progress and write plausible artifacts.

Used by the tests and, with ``MM3_FAKE_PIPELINE=1``, for UI development without ML models or
an LLM. ``MM3_FAKE_STAGE_SECONDS`` (default 2) sets how long each fake stage takes. The fakes
never touch the vault: ``FakeWrite`` only records what would have been written.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from meetingmaster3.domain.transcript import Segment, Transcript
from meetingmaster3.jobs.stage import BaseStage, Stage, StageContext

if TYPE_CHECKING:
    from meetingmaster3.config.settings import Settings

SECONDS_ENV = "MM3_FAKE_STAGE_SECONDS"
STEPS = 10

_LINES = [
    ("SPEAKER_00", "Thanks everyone for joining. Let's start with the launch status."),
    ("SPEAKER_01", "The beta build went out on Monday and feedback has been positive."),
    ("SPEAKER_00", "Great. Are there any blockers for the general release?"),
    ("SPEAKER_01", "Only the billing migration, which should land by Friday."),
    ("SPEAKER_00", "Okay, let's confirm that at Thursday's check-in."),
]


def stage_seconds() -> float:
    try:
        return max(0.0, float(os.environ.get(SECONDS_ENV, "2")))
    except ValueError:
        return 2.0


class FakeStage(BaseStage):
    """Sleeps ``seconds`` in ``STEPS`` cancellable steps, then writes ``artifact_name``."""

    artifact_name = "fake.json"

    def __init__(self, seconds: float | None = None) -> None:
        super().__init__()
        self.seconds = stage_seconds() if seconds is None else seconds

    def simulate(self, ctx: StageContext, verb: str) -> None:
        for i in range(1, STEPS + 1):
            ctx.check_cancelled()
            ctx.sleep(self.seconds / STEPS)
            ctx.progress(i / STEPS, f"{verb} ({i * 100 // STEPS}%)")

    def produce(self, ctx: StageContext) -> Any:
        return {"fake": True, "stage": self.name}

    def run(self, ctx: StageContext) -> Path:
        self.simulate(ctx, self.display_name)
        data = self.produce(ctx)
        if isinstance(data, str):
            path = ctx.artifact(self.artifact_name)
            from meetingmaster3.vault.io import atomic_write_text

            atomic_write_text(path, data, overwrite=True)
            return path
        return ctx.write_json(self.artifact_name, data)


def fake_transcript(duration: float | None = None) -> Transcript:
    step = max(4.0, (duration or 30.0) / len(_LINES))
    return Transcript(
        segments=[
            Segment(id=i, start=i * step, end=i * step + step * 0.9, speaker_label=lbl, text=t)
            for i, (lbl, t) in enumerate(_LINES)
        ],
        language="en",
        duration=duration or step * len(_LINES),
        model="fake",
        diarized=True,
    )


class FakeTranscribe(FakeStage):
    name, display_name, uses_gpu = "transcribe", "Transcribing", True
    artifact_name = "transcript.json"

    def produce(self, ctx: StageContext) -> Any:
        t = fake_transcript(ctx.job.duration_seconds)
        return json.loads(t.model_copy(update={"diarized": False}).model_dump_json())


class FakeAlign(FakeStage):
    name, display_name, uses_gpu = "align", "Aligning", True
    artifact_name = "aligned.json"

    def produce(self, ctx: StageContext) -> Any:
        return json.loads(ctx.artifacts["transcribe"].read_text(encoding="utf-8"))


class FakeDiarize(FakeStage):
    name, display_name, uses_gpu = "diarize", "Diarizing", True
    artifact_name = "transcript.final.json"

    def produce(self, ctx: StageContext) -> Any:
        return json.loads(fake_transcript(ctx.job.duration_seconds).model_dump_json())


class FakeSpeakerSuggest(FakeStage):
    name, display_name, uses_gpu = "speaker_suggest", "Speaker suggestions", True
    artifact_name = "speakers.json"

    def produce(self, ctx: StageContext) -> Any:
        t = Transcript.model_validate_json(ctx.artifacts["diarize"].read_text(encoding="utf-8"))
        return {
            "speakers": [
                {"label": label, "suggestions": [], "talk_seconds": None}
                for label in t.speaker_labels
            ]
        }


class FakeGenerate(FakeStage):
    name, display_name, uses_gpu = "generate", "Generating notes", False
    artifact_name = "notes.draft.md"

    def produce(self, ctx: StageContext) -> Any:
        answer = json.loads(ctx.artifacts["await_speaker_confirmation"].read_text("utf-8"))
        names = []
        for value in answer.get("speakers", {}).values():
            names.append(value["name"] if isinstance(value, dict) else str(value))
        title = ctx.job.title or "Fake meeting"
        people = ", ".join(names) or "unknown"
        return (
            f"# {title}\n\n**Participants:** {people}\n\n## Summary\n\n"
            "Simulated notes from the fake pipeline (MM3_FAKE_PIPELINE=1).\n"
        )


class FakeWrite(FakeStage):
    name, display_name, uses_gpu = "write", "Writing to vault", False
    artifact_name = "written.json"

    def produce(self, ctx: StageContext) -> Any:
        return {"fake": True, "note_path": None, "draft": str(ctx.artifacts["generate"])}


FAKE_STAGES: tuple[type[FakeStage], ...] = (
    FakeTranscribe,
    FakeAlign,
    FakeDiarize,
    FakeSpeakerSuggest,
    FakeGenerate,
    FakeWrite,
)


def fake_factories(seconds: float | None = None) -> dict[str, Callable[[Settings], Stage]]:
    def make(cls: type[FakeStage]) -> Callable[[Settings], Stage]:
        return lambda settings: cls(seconds)

    return {cls.name: make(cls) for cls in FAKE_STAGES}
