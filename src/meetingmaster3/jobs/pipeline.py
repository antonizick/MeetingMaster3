"""Pipelines: the ordered stages of a job type, assembled from a stage registry.

:func:`register_stage` replaces a stage's implementation (tests, plugins); an unknown stage
without one gets an :class:`UnavailableStage` that fails with an install hint. ``transcribe``,
``align`` and ``diarize`` (Phase 06) are built in: they are the WhisperX stages when the ``ml``
extra is installed, and an "engine not installed" placeholder otherwise.
``speaker_suggest`` and ``await_speaker_confirmation`` (Phase 07, :mod:`meetingmaster3.speakers`)
are always available; voice suggestions need the ``ml`` extra and opt-in voiceprints.
``generate`` and ``write`` (Phase 09, :mod:`meetingmaster3.templates.stages`) are built in too.
``MM3_FAKE_PIPELINE=1`` swaps every ML/LLM stage for a fake (generation uses the offline
:class:`~meetingmaster3.llm.fake.FakeLLMBackend`; writing still writes to the vault when one is
configured).
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from meetingmaster3.errors import MM3Error
from meetingmaster3.jobs.stage import Stage, UnavailableStage
from meetingmaster3.speakers.stages import SpeakerConfirmationStage, SpeakerSuggestStage

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
    if name == "speaker_suggest":
        return lambda settings: SpeakerSuggestStage()
    if name == "await_speaker_confirmation":
        return lambda settings: SpeakerConfirmationStage()
    if name in ("generate", "write"):

        def generation(settings: Settings) -> Stage:
            from meetingmaster3.templates.stages import GenerateStage, WriteStage

            return GenerateStage(settings) if name == "generate" else WriteStage()

        return generation
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
