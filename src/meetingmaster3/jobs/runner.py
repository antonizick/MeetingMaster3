"""The job runner: an asyncio dispatcher that runs pipeline stages in worker threads.

* Up to ``jobs.max_concurrent`` jobs are in flight; each runs its stages in order.
* A **global GPU semaphore** (size 1) is held across each contiguous run of GPU stages of a job,
  so two jobs never use the GPU at the same time and models stay loaded between
  ``transcribe → align → diarize`` (R5).
* Every completed stage records its artifact; ``resume`` restarts at the first stage that is not
  complete or whose artifact has gone (R4). On startup, jobs that were running are marked
  ``interrupted`` and queued jobs are queued again.
* ``cancel`` is cooperative: stages call ``ctx.check_cancelled()``.
* A stage raising :class:`InputRequired` pauses the job in ``waiting_for_input``;
  ``submit_input`` stores the answer and queues the job again.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, TypedDict

from pydantic import ValidationError

from meetingmaster3.config.paths import AppPaths
from meetingmaster3.config.settings import Settings
from meetingmaster3.errors import MM3Error
from meetingmaster3.jobs import retention
from meetingmaster3.jobs.files import job_dir, remove_job_dir, resolve_in_job
from meetingmaster3.jobs.models import (
    RESUMABLE,
    JobOptions,
    JobStatus,
    ProgressEvent,
    StageStatus,
    utcnow,
)
from meetingmaster3.jobs.pipeline import Pipeline, build_pipeline
from meetingmaster3.jobs.progress import ProgressBus
from meetingmaster3.jobs.stage import (
    CancelToken,
    InputRequired,
    JobCancelled,
    Stage,
    StageContext,
    input_path,
)
from meetingmaster3.jobs.vault_audio import copy_audio_to_vault
from meetingmaster3.storage.db import Database
from meetingmaster3.storage.repositories import (
    JobRecord,
    JobRepository,
    StageRecord,
    StageRepository,
)
from meetingmaster3.vault.io import atomic_write_text

log = logging.getLogger(__name__)

PipelineFactory = Callable[[str, Settings], Pipeline]
GPU_POLL_SECONDS = 0.2
SHUTDOWN_GRACE_SECONDS = 10.0


class ErrorFields(TypedDict):
    error_code: str
    error_message: str
    error_hint: str


def _error_fields(exc: BaseException) -> ErrorFields:
    if isinstance(exc, MM3Error):
        return {"error_code": exc.code, "error_message": exc.message, "error_hint": exc.hint}
    return {
        "error_code": "E_STAGE_FAILED",
        "error_message": f"{type(exc).__name__}: {exc}"[:500],
        "error_hint": "See the server log for details. You can resume the job to retry.",
    }


def _clear_errors() -> dict[str, None]:
    return {"error_code": None, "error_message": None, "error_hint": None}


class JobRunner:
    def __init__(
        self,
        db: Database,
        settings: Settings,
        paths: AppPaths,
        *,
        bus: ProgressBus | None = None,
        pipeline_factory: PipelineFactory | None = None,
        gpu_slots: int = 1,
    ) -> None:
        self.db = db
        self.settings = settings
        self.paths = paths
        self.bus = bus or ProgressBus()
        self.jobs = JobRepository(db)
        self.stages = StageRepository(db)
        self._pipeline_factory = pipeline_factory or build_pipeline
        self._gpu = asyncio.Semaphore(gpu_slots)
        self._slots = asyncio.Semaphore(settings.jobs.max_concurrent)
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._tokens: dict[str, CancelToken] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._background: list[asyncio.Task[None]] = []
        self._executor = ThreadPoolExecutor(
            max_workers=settings.jobs.max_concurrent + 1, thread_name_prefix="mm3-stage"
        )
        self._loop: asyncio.AbstractEventLoop | None = None
        self.started = False

    # -- lifecycle ---------------------------------------------------------------------

    @property
    def jobs_root(self) -> Path:
        return self.paths.jobs_dir

    def pipeline_for(self, job_type: str) -> Pipeline:
        return self._pipeline_factory(job_type, self.settings)

    async def start(self, *, prune: bool = True) -> None:
        """Recover state from a previous run, then start the dispatcher (and the pruner)."""
        self._loop = asyncio.get_running_loop()
        self.bus.bind(self._loop)
        self.recover()
        self._background.append(asyncio.create_task(self._dispatch(), name="mm3-dispatch"))
        if prune:
            self._background.append(asyncio.create_task(self._prune_loop(), name="mm3-prune"))
        self.started = True

    def recover(self) -> None:
        """Startup scan: running jobs become ``interrupted`` (resumable); queued jobs are
        queued again."""
        for job in self.jobs.list_jobs({JobStatus.RUNNING}, limit=1_000_000):
            self.jobs.set_status(
                job.id,
                JobStatus.INTERRUPTED,
                error_code="E_INTERRUPTED",
                error_message="The server stopped while this job was running.",
                error_hint="Resume the job to continue from its last completed stage.",
            )
            log.info("Job %s was interrupted at stage %s", job.id, job.current_stage)
        self.stages.mark_running_interrupted()
        for job in reversed(self.jobs.list_jobs({JobStatus.QUEUED}, limit=1_000_000)):
            self._queue.put_nowait(job.id)

    async def stop(self, timeout: float = SHUTDOWN_GRACE_SECONDS) -> None:
        """Ask running stages to stop (their jobs become ``interrupted``) and wait briefly."""
        self.started = False
        for task in self._background:
            task.cancel()
        for token in self._tokens.values():
            token.cancel(shutdown=True)
        tasks = list(self._tasks.values())
        if tasks:
            _, pending = await asyncio.wait(tasks, timeout=timeout)
            for t in pending:  # a stage ignoring cancellation; the next start marks it
                t.cancel()
        for task in self._background:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._background.clear()
        self._executor.shutdown(wait=False, cancel_futures=True)

    # -- public API ---------------------------------------------------------------------

    def create_job(
        self,
        job_id: str,
        *,
        options: JobOptions,
        source_filename: str,
        audio_name: str | None,
        duration_seconds: float | None,
        job_type: str = "meeting",
    ) -> JobRecord:
        """Register a job whose upload already sits in its folder, and queue it. An ``import``
        job has no audio (``audio_name=None``): retention, pin and the player do nothing."""
        pipeline = self.pipeline_for(job_type)
        job = self.jobs.create(
            job_id,
            stages=pipeline.names,
            title=options.title,
            meeting_date=options.meeting_date,
            source_filename=source_filename,
            audio_path=audio_name,
            duration_seconds=duration_seconds,
            settings=options.model_dump(mode="json"),
            job_type=job_type,
        )
        self._publish_job(job, "Queued")
        self._queue.put_nowait(job.id)
        return job

    def get(self, job_id: str) -> JobRecord:
        return self.jobs.get(job_id)

    def describe(self, job_id: str) -> dict[str, Any]:
        """The job, its stages (with live progress) and the input it waits for, if any."""
        job = self.jobs.get(job_id)
        latest = self.bus.latest(job_id)
        stages = []
        names = {s.name: s for s in self._safe_pipeline(job).stages}
        for rec in self.stages.for_job(job_id):
            d = rec.to_dict()
            stage = names.get(rec.stage)
            d["display_name"] = stage.display_name if stage else rec.stage
            d["uses_gpu"] = bool(stage and stage_uses_gpu(stage, job.settings))
            ev = latest.get(rec.stage) if rec.status is StageStatus.RUNNING else None
            d["fraction"] = 1.0 if rec.status is StageStatus.COMPLETED else None
            d["message"] = rec.detail.get("message", "")
            d["eta_seconds"] = None
            if ev is not None:
                d["fraction"], d["message"], d["eta_seconds"] = (
                    ev.fraction,
                    ev.message,
                    ev.eta_seconds,
                )
            stages.append(d)
        out = job.to_dict()
        out["audio"]["retention"] = self.retention_status(job).to_dict()
        out["stages"] = stages
        out["waiting_for"] = next(
            (s["detail"].get("input") for s in stages if s["status"] == StageStatus.WAITING),
            None,
        )
        out["warnings"] = [
            {"stage": s["stage"], "message": w}
            for s in stages
            for w in s["detail"].get("warnings", [])
        ]
        out["seq"] = self.bus.last_seq(job_id)
        return out

    def _safe_pipeline(self, job: JobRecord) -> Pipeline:
        try:
            return self.pipeline_for(job.job_type)
        except MM3Error:
            return Pipeline(job.job_type, ())

    async def cancel(self, job_id: str) -> JobRecord:
        job = self.jobs.get(job_id)
        token = self._tokens.get(job_id)
        if job.status is JobStatus.RUNNING and token is not None:
            token.cancel()
            task = self._tasks.get(job_id)
            if task is not None:
                await asyncio.wait({task}, timeout=SHUTDOWN_GRACE_SECONDS)
            return self.jobs.get(job_id)
        if job.status not in {
            JobStatus.QUEUED,
            JobStatus.WAITING_FOR_INPUT,
            JobStatus.INTERRUPTED,
        }:
            raise MM3Error(
                "E_JOB_STATE",
                f"A {job.status.value} job cannot be cancelled.",
                "Only queued, running, waiting or interrupted jobs can be cancelled.",
                status_code=409,
            )
        if token is not None:  # queued and already picked up by the dispatcher
            token.cancel()
        job = self.jobs.set_status(job_id, JobStatus.CANCELLED, expected={job.status})
        for rec in self.stages.for_job(job_id):
            if rec.status in {StageStatus.WAITING, StageStatus.INTERRUPTED}:
                self.stages.update(job_id, rec.stage, status=StageStatus.CANCELLED)
        self._publish_job(job, "Cancelled")
        return job

    def resume(
        self,
        job_id: str,
        overrides: dict[str, Any] | None = None,
        *,
        from_stage: str | None = None,
    ) -> JobRecord:
        """Queue a failed, cancelled or interrupted job again; ``overrides`` are merged into
        its options (e.g. a smaller model after an out-of-memory failure). ``from_stage`` also
        re-runs that stage and every later one, even if they completed (e.g. ``generate`` with
        another template)."""
        job = self.jobs.get(job_id)
        if job.status not in RESUMABLE:
            raise MM3Error(
                "E_JOB_STATE",
                f"A {job.status.value} job cannot be resumed.",
                "Only failed, cancelled or interrupted jobs can be resumed.",
                status_code=409,
            )
        if from_stage is not None:
            rows = {r.stage: r for r in self.stages.for_job(job_id)}
            if from_stage not in rows:
                raise MM3Error(
                    "E_STAGE_UNKNOWN", f"This job has no stage {from_stage!r}.", "", status_code=422
                )
            self.stages.reset_from(job_id, rows[from_stage].position)
            # Answers given to the stages that re-run are stale (a cloud consent, speaker names
            # for labels that may change): they will be asked again if still needed.
            folder = job_dir(self.jobs_root, job_id)
            for row in rows.values():
                if row.position >= rows[from_stage].position:
                    input_path(folder, row.stage).unlink(missing_ok=True)
        fields: dict[str, Any] = _clear_errors()
        if overrides:
            fields["settings"] = self._merge_options(job, overrides)
        job = self.jobs.set_status(job_id, JobStatus.QUEUED, expected={job.status}, **fields)
        self._publish_job(job, "Queued to resume")
        self._queue.put_nowait(job_id)
        return job

    def update_options(self, job_id: str, overrides: dict[str, Any]) -> JobRecord:
        """Change the options of a queued or waiting job; they apply to the stages still to
        run (e.g. the template before ``generate``)."""
        job = self.jobs.get(job_id)
        if job.status not in {JobStatus.QUEUED, JobStatus.WAITING_FOR_INPUT}:
            raise MM3Error(
                "E_JOB_STATE",
                f"The options of a {job.status.value} job cannot be changed.",
                "Wait for the job to pause or finish, or resume it with new options.",
                status_code=409,
            )
        return self.jobs.update(job_id, settings=self._merge_options(job, overrides))

    def waiting_stage(self, job_id: str) -> str | None:
        """The stage a ``waiting_for_input`` job is waiting in."""
        waiting = [r for r in self.stages.for_job(job_id) if r.status is StageStatus.WAITING]
        return waiting[0].stage if waiting else None

    def submit_input(self, job_id: str, data: dict[str, Any]) -> JobRecord:
        """Answer the question a ``waiting_for_input`` job is waiting on, and queue it."""
        job = self.jobs.get(job_id)
        waiting = [r for r in self.stages.for_job(job_id) if r.status is StageStatus.WAITING]
        if job.status is not JobStatus.WAITING_FOR_INPUT or not waiting:
            raise MM3Error(
                "E_JOB_STATE",
                "This job is not waiting for input.",
                "Refresh the job; it may have been answered already.",
                status_code=409,
            )
        stage = self.pipeline_for(job.job_type).stage(waiting[0].stage)
        validate = getattr(stage, "validate_input", None)
        if callable(validate):
            data = validate(data)
        folder = job_dir(self.jobs_root, job_id)
        atomic_write_text(input_path(folder, stage.name), _json(data), overwrite=True)
        job = self.jobs.set_status(
            job_id, JobStatus.QUEUED, expected={JobStatus.WAITING_FOR_INPUT}, **_clear_errors()
        )
        self._publish_job(job, "Input received")
        self._queue.put_nowait(job_id)
        return job

    def delete(self, job_id: str, *, force: bool = False) -> None:
        """Delete a job's folder (audio and artifacts) and its rows. Notes already written to
        the vault are not touched."""
        job = self.jobs.get(job_id)
        if job.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
            raise MM3Error(
                "E_JOB_ACTIVE",
                "This job is still active.",
                "Cancel the job first, then delete it.",
                status_code=409,
            )
        if job.audio_pinned and job.audio_path and not force:
            raise MM3Error(
                "E_JOB_PINNED",
                "This meeting's audio is pinned.",
                "Unpin it first, or delete with force=true.",
                status_code=409,
            )
        remove_job_dir(self.jobs_root, job_id)
        self.jobs.delete(job_id)
        self.bus.forget(job_id)

    def retention_status(self, job: JobRecord) -> retention.RetentionStatus:
        return retention.audio_retention_status(job, self.settings.privacy)

    def set_pinned(self, job_id: str, pinned: bool) -> JobRecord:
        job = self.jobs.get(job_id)
        if pinned and job.audio_path is None and job.audio_pruned_at is not None:
            raise retention.audio_expired_error()
        return self.jobs.update(job_id, audio_pinned=pinned)

    def prune(self, *, dry_run: bool = False) -> list[retention.PruneItem]:
        return retention.prune(self.jobs, self.jobs_root, self.settings, dry_run=dry_run)

    def audio_file(self, job_id: str) -> Path:
        job = self.jobs.get(job_id)
        if job.audio_path is None:
            if job.audio_pruned_at is not None:
                raise retention.audio_expired_error()
            raise MM3Error("E_AUDIO_MISSING", "This job has no audio.", "", status_code=404)
        path = retention.playable_audio(job_dir(self.jobs_root, job_id), job)
        if path is None:
            raise MM3Error(
                "E_AUDIO_MISSING",
                "The audio file for this job is missing from the data folder.",
                "It may have been deleted outside MeetingMaster3.",
                status_code=404,
            )
        return path

    # -- internals --------------------------------------------------------------------

    def _merge_options(self, job: JobRecord, overrides: dict[str, Any]) -> dict[str, Any]:
        try:
            merged = JobOptions.model_validate({**job.settings, **overrides})
        except ValidationError as exc:
            raise MM3Error(
                "E_OPTIONS_INVALID",
                f"Invalid job options: {exc.errors()[0].get('msg', 'invalid value')}",
                "Check the option names and values.",
                status_code=422,
            ) from exc
        return merged.model_dump(mode="json")

    def _publish_job(self, job: JobRecord, message: str = "", **data: Any) -> None:
        self.bus.publish(
            ProgressEvent(
                job_id=job.id,
                stage=job.current_stage,
                status=job.status.value,
                message=message,
                kind="job",
                data={"error": job.to_dict()["error"], **data},
            )
        )

    def _publish_stage(
        self,
        job_id: str,
        stage: str,
        status: StageStatus,
        fraction: float | None = None,
        message: str = "",
        eta: float | None = None,
        **data: Any,
    ) -> None:
        self.bus.publish(
            ProgressEvent(job_id, stage, status.value, fraction, message, eta, data=data)
        )

    async def _dispatch(self) -> None:
        while True:
            job_id = await self._queue.get()
            if job_id in self._tasks:  # already running (a duplicate queue entry)
                continue
            await self._slots.acquire()
            job = self.jobs.find(job_id)
            if job is None or job.status is not JobStatus.QUEUED:
                self._slots.release()
                continue
            token = CancelToken()
            self._tokens[job_id] = token
            task = asyncio.create_task(self._run_job_guarded(job_id, token), name=f"job-{job_id}")
            self._tasks[job_id] = task

    async def _run_job_guarded(self, job_id: str, token: CancelToken) -> None:
        try:
            await self._run_job(job_id, token)
        except asyncio.CancelledError:
            pass  # stop() gave up waiting; the next start marks the job interrupted
        except Exception:  # pragma: no cover - a bug in the runner itself
            log.exception("Runner error for job %s", job_id)
        finally:
            self._tokens.pop(job_id, None)
            self._tasks.pop(job_id, None)
            self._slots.release()

    def _start_position(self, job: JobRecord, pipeline: Pipeline, rows: list[StageRecord]) -> int:
        if [r.stage for r in rows] != pipeline.names:
            raise MM3Error(
                "E_PIPELINE_CHANGED",
                "This job was created by a different version of MeetingMaster3 and its stages "
                "no longer match.",
                "Delete the job and upload the recording again.",
                status_code=409,
            )
        folder = job_dir(self.jobs_root, job.id)
        for rec in rows:
            done = rec.status is StageStatus.COMPLETED
            artifact = resolve_in_job(folder, rec.artifact_path)
            if not done or artifact is None or not artifact.exists():
                self.stages.reset_from(job.id, rec.position)
                return rec.position
        return len(rows)

    def gpu_idle(self) -> bool:
        """No job is running or queued, and nothing holds the GPU."""
        return not self._tasks and self._queue.empty() and not self._gpu.locked()

    @contextlib.asynccontextmanager
    async def background_gpu(self, poll_s: float = 1.0) -> AsyncIterator[None]:
        """The GPU for low-priority work (search indexing with a local embedder, Phase 15i).

        It is taken only while no job is running or queued, and held for one short batch, so a
        job that arrives waits at most that batch (R5)."""
        while not self.gpu_idle():
            await asyncio.sleep(poll_s)
        await self._gpu.acquire()
        try:
            yield
        finally:
            self._gpu.release()

    async def _acquire_gpu(self, token: CancelToken) -> None:
        while True:
            if token.cancelled:
                raise JobCancelled("cancelled while waiting for the GPU")
            try:
                await asyncio.wait_for(self._gpu.acquire(), GPU_POLL_SECONDS)
                return
            except TimeoutError:
                continue

    async def _run_job(self, job_id: str, token: CancelToken) -> None:
        try:
            job = self.jobs.set_status(job_id, JobStatus.RUNNING, expected={JobStatus.QUEUED})
        except MM3Error:
            return  # cancelled between queueing and starting
        self._publish_job(job, "Started")
        gpu_held = False
        current: str | None = None
        try:
            pipeline = self.pipeline_for(job.job_type)
            rows = self.stages.for_job(job_id)
            start = self._start_position(job, pipeline, rows)
            folder = job_dir(self.jobs_root, job_id, create=True)
            artifacts: dict[str, Path] = {}
            for rec in rows[:start]:
                path = resolve_in_job(folder, rec.artifact_path)
                if path is not None:
                    artifacts[rec.stage] = path
            for stage in pipeline.stages[start:]:
                current = stage.name
                if token.cancelled:
                    raise JobCancelled(job_id)
                uses_gpu = stage_uses_gpu(stage, job.settings)
                if uses_gpu and not gpu_held:
                    self._publish_stage(
                        job_id, stage.name, StageStatus.PENDING, None, "Waiting for the GPU"
                    )
                    await self._acquire_gpu(token)
                    gpu_held = True
                elif not uses_gpu and gpu_held:
                    self._gpu.release()
                    gpu_held = False
                artifacts[stage.name] = await self._run_stage(job_id, stage, artifacts, token)
            if gpu_held:
                self._gpu.release()
                gpu_held = False
            await self._finish(job_id)
        except JobCancelled:
            new = JobStatus.INTERRUPTED if token.shutdown else JobStatus.CANCELLED
            fields: dict[str, Any] = _clear_errors()
            if token.shutdown:
                fields.update(
                    error_code="E_INTERRUPTED",
                    error_message="The server stopped while this job was running.",
                    error_hint="Resume the job to continue from its last completed stage.",
                )
            if current is not None:
                rec = self.stages.get(job_id, current)
                if rec.status in {StageStatus.PENDING, StageStatus.RUNNING}:
                    self.stages.update(job_id, current, status=StageStatus(new.value))
            job = self.jobs.set_status(job_id, new, **fields)
            self._publish_job(job, "Interrupted" if token.shutdown else "Cancelled")
        except InputRequired as req:
            job = self.jobs.set_status(job_id, JobStatus.WAITING_FOR_INPUT)
            self._publish_job(job, "Waiting for input", input={"kind": req.kind, **req.payload})
        except Exception as exc:
            if not isinstance(exc, MM3Error):
                log.exception("Job %s failed in stage %s", job_id, current)
            job = self.jobs.set_status(job_id, JobStatus.FAILED, **_error_fields(exc))
            self._publish_job(job, "Failed")
        finally:
            if gpu_held:
                self._gpu.release()

    async def _run_stage(
        self, job_id: str, stage: Stage, artifacts: dict[str, Path], token: CancelToken
    ) -> Path:
        loop = asyncio.get_running_loop()
        folder = job_dir(self.jobs_root, job_id)
        attempt = 0
        while True:
            attempt += 1
            job = self.jobs.update(job_id, current_stage=stage.name)
            self.stages.update(
                job_id,
                stage.name,
                status=StageStatus.RUNNING,
                started_at=utcnow(),
                finished_at=None,
                artifact_path=None,
                attempt=attempt,
                detail={},
            )
            self.bus.eta.start(job_id, stage.name)
            self._publish_stage(job_id, stage.name, StageStatus.RUNNING, 0.0, "Started")

            def report(
                fraction: float | None, message: str, eta: float | None, _name: str = stage.name
            ) -> None:
                if eta is None:
                    eta = self.bus.eta.estimate(job_id, _name, fraction)
                self._publish_stage(job_id, _name, StageStatus.RUNNING, fraction, message, eta)

            ctx = StageContext(
                job=job,
                stage=stage.name,
                job_dir=folder,
                settings=self.settings,
                options=dict(job.settings),
                artifacts=dict(artifacts),
                attempt=attempt,
                token=token,
                _progress=report,
                db=self.db,
            )
            try:
                result = await loop.run_in_executor(self._executor, stage.run, ctx)
            except JobCancelled:
                self.bus.eta.stop(job_id, stage.name)
                status = StageStatus.INTERRUPTED if token.shutdown else StageStatus.CANCELLED
                self.stages.update(job_id, stage.name, status=status, finished_at=utcnow())
                self._publish_stage(job_id, stage.name, status)
                raise
            except InputRequired as req:
                self.bus.eta.stop(job_id, stage.name)
                question = {"kind": req.kind, "stage": stage.name, **req.payload}
                self.stages.update(
                    job_id, stage.name, status=StageStatus.WAITING, detail={"input": question}
                )
                self._publish_stage(
                    job_id, stage.name, StageStatus.WAITING, None, "Waiting for input",
                    input=question,
                )  # fmt: skip
                raise
            except Exception as exc:
                retry = await self._should_retry(stage, ctx, exc)
                if ctx.options != job.settings:
                    self.jobs.update(job_id, settings=ctx.options)
                if retry and not token.cancelled:
                    log.info(
                        "Retrying stage %s of job %s (attempt %d)", stage.name, job_id, attempt
                    )
                    self._publish_stage(
                        job_id, stage.name, StageStatus.RUNNING, 0.0,
                        f"Retrying after: {_error_fields(exc)['error_message']}",
                    )  # fmt: skip
                    continue
                self.bus.eta.stop(job_id, stage.name)
                err = _error_fields(exc)
                failed: dict[str, Any] = {"error": dict(err)}
                if isinstance(exc, MM3Error) and exc.details:
                    failed["error"]["details"] = exc.details
                if ctx.warnings:
                    failed["warnings"] = ctx.warnings
                self.stages.update(
                    job_id,
                    stage.name,
                    status=StageStatus.FAILED,
                    finished_at=utcnow(),
                    detail=failed,
                )
                self._publish_stage(
                    job_id, stage.name, StageStatus.FAILED, None, err["error_message"], error=err
                )
                raise
            self.bus.eta.stop(job_id, stage.name)
            if ctx.options != job.settings:
                self.jobs.update(job_id, settings=ctx.options)
            artifact = resolve_in_job(folder, Path(result).name)
            if (
                artifact is None
                or Path(result).resolve() != artifact.resolve()
                or not artifact.exists()
            ):
                err_exc = MM3Error(
                    "E_STAGE_ARTIFACT",
                    f"Stage {stage.name} did not leave its result in the job folder.",
                    "This is a bug; please report it.",
                    status_code=500,
                )
                self.stages.update(
                    job_id, stage.name, status=StageStatus.FAILED, finished_at=utcnow(),
                    detail={"error": _error_fields(err_exc)},
                )  # fmt: skip
                raise err_exc
            self.stages.update(
                job_id,
                stage.name,
                status=StageStatus.COMPLETED,
                finished_at=utcnow(),
                artifact_path=artifact.name,
                detail={"message": "Done", **({"warnings": ctx.warnings} if ctx.warnings else {})},
            )
            extra: dict[str, Any] = {"warnings": ctx.warnings} if ctx.warnings else {}
            self._publish_stage(job_id, stage.name, StageStatus.COMPLETED, 1.0, "Done", **extra)
            return artifact

    async def _should_retry(self, stage: Stage, ctx: StageContext, exc: Exception) -> bool:
        try:
            return bool(
                await asyncio.get_running_loop().run_in_executor(
                    self._executor, stage.should_retry, ctx, exc
                )
            )
        except Exception:
            log.exception("Retry hook of stage %s failed", stage.name)
            return False

    async def _finish(self, job_id: str) -> None:
        written_at = utcnow()
        job = self.jobs.get(job_id)
        loop = asyncio.get_running_loop()
        job = await loop.run_in_executor(
            self._executor,
            retention.finalize_audio,
            self.jobs,
            self.jobs_root,
            job,
            self.settings,
            written_at,
        )
        job = self.jobs.set_status(
            job_id, JobStatus.WRITTEN, current_stage=None, written_at=written_at
        )
        if self.settings.privacy.copy_audio_to_vault:
            await loop.run_in_executor(
                self._executor, copy_audio_to_vault, self.jobs_root, job, self.settings
            )
        if self.settings.privacy.audio_retention == "delete_after_write":
            await loop.run_in_executor(self._executor, self.prune)
            job = self.jobs.get(job_id)
        self._publish_job(job, "Finished")

    async def _prune_loop(self) -> None:
        interval = self.settings.jobs.prune_interval_hours * 3600
        loop = asyncio.get_running_loop()
        while True:
            try:
                items = await loop.run_in_executor(self._executor, self.prune)
                if items:
                    log.info("Audio retention pruned %d job(s)", len(items))
            except Exception:
                log.exception("Audio retention pruning failed")
            await asyncio.sleep(interval)


def stage_uses_gpu(stage: Stage, options: dict[str, Any]) -> bool:
    """Whether ``stage`` needs the GPU for a job with these options. A stage can decide per
    job with ``gpu_for(options)`` (the generate stage, when the job's backend is a local Ollama
    sharing the GPU); otherwise its ``uses_gpu`` attribute applies."""
    decide = getattr(stage, "gpu_for", None)
    if callable(decide):
        return bool(decide(options))
    return bool(stage.uses_gpu)


def _json(data: Any) -> str:
    import json

    return json.dumps(data, indent=2, default=str) + "\n"
