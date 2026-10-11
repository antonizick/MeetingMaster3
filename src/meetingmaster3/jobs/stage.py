"""The ``Stage`` protocol, the context a stage runs with, and stage control-flow exceptions.

A stage is a unit of checkpointed work. ``run(ctx)`` executes in a worker thread, writes its
output artifact inside ``ctx.job_dir`` and returns that path. The runner records the artifact,
so after a restart a completed stage whose artifact still exists is never run again (R4).
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from meetingmaster3.errors import MM3Error
from meetingmaster3.vault.io import atomic_write_text

if TYPE_CHECKING:
    from meetingmaster3.config.settings import Settings
    from meetingmaster3.storage.db import Database
    from meetingmaster3.storage.repositories import JobRecord


class JobCancelled(Exception):
    """Raised by :meth:`StageContext.check_cancelled` after a cancel (or a shutdown)."""


class InputRequired(Exception):
    """Raised by a stage that needs a human decision. The job pauses in ``waiting_for_input``;
    ``JobRunner.submit_input`` saves the answer and re-runs the stage, which then finds it with
    :meth:`StageContext.input`.

    ``kind`` names the question (``speaker_confirmation``, ``language``…) and ``payload`` is
    shown to the UI."""

    def __init__(self, kind: str, payload: dict[str, Any] | None = None) -> None:
        super().__init__(kind)
        self.kind = kind
        self.payload = payload or {}


class CancelToken:
    """A cancel flag readable from worker threads. ``shutdown`` distinguishes a server stop
    (the job becomes ``interrupted``) from a user cancel (``cancelled``)."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self.shutdown = False

    def cancel(self, *, shutdown: bool = False) -> None:
        self.shutdown = self.shutdown or shutdown
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def wait(self, timeout: float) -> bool:
        """Sleep up to ``timeout`` seconds; return True early if cancelled."""
        return self._event.wait(timeout)


ProgressFn = Callable[[float | None, str, float | None], None]


@dataclass
class StageContext:
    """What a stage gets: the job, its folder, options, earlier artifacts and controls."""

    job: JobRecord
    stage: str
    job_dir: Path
    settings: Settings
    options: dict[str, Any]
    artifacts: dict[str, Path]  # artifacts of completed earlier stages, by stage name
    attempt: int
    token: CancelToken
    _progress: ProgressFn
    db: Database | None = None  # app database, e.g. for RecentMeetingsRepository (Phase 09)
    log: logging.Logger = field(default_factory=lambda: logging.getLogger("meetingmaster3.jobs"))

    @property
    def job_id(self) -> str:
        return self.job.id

    def check_cancelled(self) -> None:
        """Call between chunks of work. Raises :class:`JobCancelled` if the job was cancelled
        or the server is stopping."""
        if self.token.cancelled:
            raise JobCancelled(self.job_id)

    def progress(
        self, fraction: float | None, message: str = "", eta_seconds: float | None = None
    ) -> None:
        """Report progress in ``[0, 1]`` (``None`` = indeterminate). The ETA is estimated
        from the rate when not given."""
        if fraction is not None:
            fraction = min(1.0, max(0.0, float(fraction)))
        self._progress(fraction, message, eta_seconds)

    def sleep(self, seconds: float) -> None:
        """Cancellable sleep (for fakes and polling loops)."""
        if self.token.wait(seconds):
            raise JobCancelled(self.job_id)

    def artifact(self, name: str) -> Path:
        """The path for a new artifact file in this job's folder (``name`` is a bare name)."""
        if not name or "/" in name or "\\" in name or name in {".", ".."}:
            raise ValueError(f"artifact name must be a bare file name: {name!r}")
        return self.job_dir / name

    def write_json(self, name: str, data: Any) -> Path:
        """Atomically write ``data`` as JSON to the artifact ``name`` and return its path."""
        path = self.artifact(name)
        atomic_write_text(path, json.dumps(data, indent=2, default=str) + "\n", overwrite=True)
        return path

    def input(self) -> dict[str, Any] | None:
        """The answer submitted for this stage's :class:`InputRequired`, if any."""
        path = input_path(self.job_dir, self.stage)
        if not path.is_file():
            return None
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return data


def input_path(job_dir: Path, stage: str) -> Path:
    return job_dir / f"input.{stage}.json"


@runtime_checkable
class Stage(Protocol):
    """One checkpointed step of a pipeline."""

    name: str  # stable id, stored in job_stages.stage
    display_name: str  # shown in the UI ("Transcribing")
    uses_gpu: bool  # GPU stages are serialised by the runner's global GPU semaphore

    def run(self, ctx: StageContext) -> Path:
        """Do the work (in a worker thread) and return the artifact path."""
        ...

    def should_retry(self, ctx: StageContext, exc: Exception) -> bool:
        """Retry hook, called after ``run`` raised ``exc`` on attempt ``ctx.attempt``.

        Return True to run the stage again (a stage may first change ``ctx.options``, which are
        persisted, e.g. a smaller batch size after CUDA OOM). Return False to fail the job."""
        ...


class BaseStage:
    """Convenience base: no retries, CPU-only, ``display_name`` defaults to ``name``."""

    name: str = ""
    display_name: str = ""
    uses_gpu: bool = False

    def __init__(self) -> None:
        if not self.display_name:
            self.display_name = self.name.replace("_", " ").capitalize()

    def run(self, ctx: StageContext) -> Path:  # pragma: no cover - abstract
        raise NotImplementedError

    def should_retry(self, ctx: StageContext, exc: Exception) -> bool:
        return False


class AwaitInputStage(BaseStage):
    """A human-in-the-loop pause. The first run raises :class:`InputRequired`; after the answer
    arrives the stage completes with the saved answer as its artifact."""

    kind = "input"

    def __init__(self, name: str, display_name: str, kind: str) -> None:
        self.name, self.display_name, self.kind = name, display_name, kind
        super().__init__()

    def payload(self, ctx: StageContext) -> dict[str, Any]:
        """What the UI needs to ask the question (e.g. the suggested speaker map)."""
        return {}

    def validate_input(self, data: dict[str, Any]) -> dict[str, Any]:
        """Check (and normalise) a submitted answer; raise ``MM3Error`` if it is unusable."""
        return data

    def run(self, ctx: StageContext) -> Path:
        if ctx.input() is None:
            raise InputRequired(self.kind, self.payload(ctx))
        return input_path(ctx.job_dir, self.name)


class UnavailableStage(BaseStage):
    """Placeholder for a stage whose implementation is not installed or not built yet."""

    def __init__(self, name: str, display_name: str, uses_gpu: bool = False) -> None:
        self.name, self.display_name, self.uses_gpu = name, display_name, uses_gpu
        super().__init__()

    def run(self, ctx: StageContext) -> Path:
        raise MM3Error(
            "E_STAGE_UNAVAILABLE",
            f"The {self.display_name.lower()} step is not available in this installation.",
            "Install the transcription engine with `uv sync --extra ml` (see the installation "
            "guide), or start the server with MM3_FAKE_PIPELINE=1 to try the app with "
            "simulated results.",
            status_code=500,
        )
