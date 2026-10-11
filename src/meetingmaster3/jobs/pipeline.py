"""Pipelines: the ordered stages of a job type, assembled from a stage registry.

Later phases plug in real stages with :func:`register_stage` (Phase 07: ``speaker_suggest`` and
the confirmation input; Phase 09: ``generate``, ``write``). Until a stage is registered, an
:class:`UnavailableStage` stands in and fails with an install hint. ``transcribe``, ``align`` and
``diarize`` (Phase 06) are built in: they are the WhisperX stages when the ``ml`` extra is
installed, and an "engine not installed" placeholder otherwise. ``MM3_FAKE_PIPELINE=1`` swaps
every ML/LLM stage for a fake.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from meetingmaster3.errors import MM3Error
from meetingmaster3.jobs.stage import AwaitInputStage, Stage, StageContext, UnavailableStage

if TYPE_CHECKING:
    from meetingmaster3.config.settings import Settings

FAKE_ENV = "MM3_FAKE_PIPELINE"

#: Canonical stage order of a ``meeting`` job (stage name, display name, uses GPU).
MEETING_STAGES: list[tuple[str, str, bool]] = [
    ("ingest", "Preparing audio", False),
    ("transcribe", "Transcribing", True),
    ("align", "Aligning", True),
    ("diarize", "Diarizing", True),
    ("speaker_suggest", "Speaker suggestions", True),
    ("await_speaker_confirmation", "Confirm speakers", False),
    ("generate", "Generating notes", False),
    ("write", "Writing to vault", False),
]

TRANSCRIPTION_STAGES = frozenset({"transcribe", "align", "diarize"})

StageFactory = Callable[["Settings"], Stage]
_REGISTRY: dict[str, StageFactory] = {}


def register_stage(name: str, factory: StageFactory) -> None:
    """Install the implementation of stage ``name`` (replacing any earlier one)."""
    _REGISTRY[name] = factory


def unregister_stage(name: str) -> None:
    _REGISTRY.pop(name, None)


def fake_pipeline_enabled() -> bool:
    return os.environ.get(FAKE_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


class SpeakerConfirmationStage(AwaitInputStage):
    """Pauses the job until the user confirms speaker names.

    Phase 04 accepts ``{"speakers": {"SPEAKER_00": "Alice" | {"name": "Alice", ...}}}`` and
    shows the labels found in ``speakers.json``; Phase 07 extends the payload and validation."""

    def __init__(self) -> None:
        super().__init__("await_speaker_confirmation", "Confirm speakers", "speaker_confirmation")

    def payload(self, ctx: StageContext) -> dict[str, Any]:
        import json

        path = ctx.artifacts.get("speaker_suggest")
        if path is not None and path.is_file():
            data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
            return data
        return {}

    def validate_input(self, data: dict[str, Any]) -> dict[str, Any]:
        speakers = data.get("speakers")
        if not isinstance(speakers, dict) or not all(isinstance(k, str) for k in speakers):
            raise MM3Error(
                "E_INPUT_INVALID",
                'Expected {"speakers": {"<label>": "<name>" | {"name": "<name>"}}}.',
                "Send one entry per speaker label shown in the job's waiting payload.",
                status_code=422,
            )
        for label, value in speakers.items():
            name = value.get("name") if isinstance(value, dict) else value
            if not isinstance(name, str) or not name.strip() or len(name) > 200:
                raise MM3Error(
                    "E_INPUT_INVALID",
                    f"Speaker {label!r} needs a non-empty name (up to 200 characters).",
                    "Type a name for every speaker, or keep the suggested placeholder.",
                    status_code=422,
                )
        return data


def _default_factory(name: str, display: str, gpu: bool) -> StageFactory:
    if name == "ingest":

        def ingest(settings: Settings) -> Stage:
            from meetingmaster3.audio.stage import IngestStage

            return IngestStage()

        return ingest
    if name in TRANSCRIPTION_STAGES:

        def transcription(settings: Settings) -> Stage:
            from meetingmaster3.transcription.stages import build_stage

            return build_stage(name, display, settings)

        return transcription
    if name == "await_speaker_confirmation":
        return lambda settings: SpeakerConfirmationStage()
    return lambda settings: UnavailableStage(name, display, uses_gpu=gpu)


@dataclass(frozen=True)
class Pipeline:
    job_type: str
    stages: tuple[Stage, ...]

    @property
    def names(self) -> list[str]:
        return [s.name for s in self.stages]

    def stage(self, name: str) -> Stage:
        for s in self.stages:
            if s.name == name:
                return s
        raise KeyError(name)


def build_pipeline(job_type: str, settings: Settings, *, fake: bool | None = None) -> Pipeline:
    """The pipeline for ``job_type`` (only ``meeting`` exists in the MVP)."""
    if job_type != "meeting":
        raise MM3Error("E_JOB_TYPE", f"Unknown job type {job_type!r}.", "", status_code=400)
    fake = fake_pipeline_enabled() if fake is None else fake
    fakes: dict[str, StageFactory] = {}
    if fake:
        from meetingmaster3.jobs.fakes import fake_factories

        fakes = fake_factories()
    stages: list[Stage] = []
    for name, display, gpu in MEETING_STAGES:
        factory = fakes.get(name) or _REGISTRY.get(name) or _default_factory(name, display, gpu)
        stages.append(factory(settings))
    return Pipeline(job_type, tuple(stages))
