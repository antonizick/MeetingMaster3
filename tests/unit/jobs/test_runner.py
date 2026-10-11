from __future__ import annotations

import asyncio
import itertools
import json
import threading
from pathlib import Path

import pytest

from meetingmaster3.config.settings import Settings
from meetingmaster3.errors import MM3Error
from meetingmaster3.jobs.files import job_dir
from meetingmaster3.jobs.models import JobStatus, StageStatus
from meetingmaster3.jobs.stage import InputRequired, StageContext
from meetingmaster3.storage.db import Database

from .helpers import Log, RecStage, add_job, make_runner, standard_stages, wait_status

SPEAKERS = {"speakers": {"SPEAKER_00": "Alice"}}


def stage_statuses(runner, job_id):  # type: ignore[no-untyped-def]
    return {r.stage: r.status for r in runner.stages.for_job(job_id)}


async def test_happy_path_pauses_for_input_then_finishes(tmp_path: Path) -> None:
    log = Log()
    runner = make_runner(tmp_path, standard_stages(log))
    await runner.start(prune=False)
    try:
        job_id = add_job(runner)
        await wait_status(runner, job_id, JobStatus.WAITING_FOR_INPUT)
        assert log.names() == ["ingest", "transcribe", "diarize"]
        desc = runner.describe(job_id)
        assert desc["waiting_for"]["kind"] == "speaker_confirmation"
        assert stage_statuses(runner, job_id)["await_speaker_confirmation"] is StageStatus.WAITING

        runner.submit_input(job_id, SPEAKERS)
        await wait_status(runner, job_id, JobStatus.WRITTEN)
        assert log.names() == ["ingest", "transcribe", "diarize", "generate", "write"]
        assert set(stage_statuses(runner, job_id).values()) == {StageStatus.COMPLETED}
        job = runner.jobs.get(job_id)
        assert job.written_at is not None and job.current_stage is None
        folder = job_dir(runner.jobs_root, job_id)
        answer = json.loads((folder / "input.await_speaker_confirmation.json").read_text())
        assert answer == SPEAKERS
    finally:
        await runner.stop()


async def test_input_is_validated_and_only_accepted_while_waiting(tmp_path: Path) -> None:
    runner = make_runner(tmp_path, standard_stages(Log()))
    await runner.start(prune=False)
    try:
        job_id = add_job(runner)
        await wait_status(runner, job_id, JobStatus.WAITING_FOR_INPUT)
        with pytest.raises(MM3Error) as bad:
            runner.submit_input(job_id, {"speakers": {"SPEAKER_00": "  "}})
        assert bad.value.code == "E_INPUT_INVALID"
        with pytest.raises(MM3Error):
            runner.submit_input(job_id, {"nope": 1})
        runner.submit_input(job_id, SPEAKERS)
        await wait_status(runner, job_id, JobStatus.WRITTEN)
        with pytest.raises(MM3Error) as late:
            runner.submit_input(job_id, SPEAKERS)
        assert late.value.code == "E_JOB_STATE"
    finally:
        await runner.stop()


async def test_resume_after_crash_skips_completed_stages(tmp_path: Path) -> None:
    """Kill mid-stage (the runner vanishes without cleanup), restart, resume."""
    log = Log()
    block = threading.Event()
    crashing = standard_stages(log)
    crashing[2] = RecStage("diarize", log, gpu=True, block=block)
    paths_db = tmp_path / "data" / "mm3.db"
    first = make_runner(tmp_path, crashing)
    await first.start(prune=False)
    job_id = add_job(first)
    await asyncio.to_thread(crashing[2].entered.wait, 5)  # type: ignore[attr-defined]
    assert first.jobs.get(job_id).status is JobStatus.RUNNING
    # Simulated crash: no stop(), the old runner's state is simply abandoned.
    for task in first._background:
        task.cancel()
    first._tokens[job_id].cancel()  # let the orphaned worker thread exit; DB is ignored below
    for t in list(first._tasks.values()):
        t.cancel()
    await asyncio.sleep(0.05)
    # Put the DB back into the state a hard kill would leave.
    first.jobs.db.execute("UPDATE jobs SET status = 'running' WHERE id = ?", (job_id,))
    first.jobs.db.execute(
        "UPDATE job_stages SET status = 'running' WHERE job_id = ? AND stage = 'diarize'",
        (job_id,),
    )

    log2 = Log()
    second = make_runner(tmp_path, standard_stages(log2), db=Database.open(paths_db))
    await second.start(prune=False)
    try:
        job = second.jobs.get(job_id)
        assert job.status is JobStatus.INTERRUPTED and job.error_code == "E_INTERRUPTED"
        assert stage_statuses(second, job_id)["diarize"] is StageStatus.INTERRUPTED
        second.resume(job_id)
        await wait_status(second, job_id, JobStatus.WAITING_FOR_INPUT)
        assert log2.names() == ["diarize"]  # ingest and transcribe were not redone
        second.submit_input(job_id, SPEAKERS)
        await wait_status(second, job_id, JobStatus.WRITTEN)
        assert log2.names() == ["diarize", "generate", "write"]
    finally:
        block.set()
        await second.stop()
        await first.stop(timeout=1)


async def test_missing_artifact_reruns_that_stage_and_later_ones(tmp_path: Path) -> None:
    log = Log()
    runner = make_runner(tmp_path, standard_stages(log))
    await runner.start(prune=False)
    try:
        job_id = add_job(runner)
        await wait_status(runner, job_id, JobStatus.WAITING_FOR_INPUT)
        await runner.cancel(job_id)
        (job_dir(runner.jobs_root, job_id) / "transcribe.json").unlink()
        runner.resume(job_id)
        await wait_status(runner, job_id, JobStatus.WAITING_FOR_INPUT)
        assert log.names() == ["ingest", "transcribe", "diarize", "transcribe", "diarize"]
    finally:
        await runner.stop()


async def test_cancel_running_job(tmp_path: Path) -> None:
    log = Log()
    block = threading.Event()
    stages = standard_stages(log)
    stages[1] = RecStage("transcribe", log, gpu=True, block=block)
    runner = make_runner(tmp_path, stages)
    await runner.start(prune=False)
    try:
        job_id = add_job(runner)
        await asyncio.to_thread(stages[1].entered.wait, 5)  # type: ignore[attr-defined]
        job = await runner.cancel(job_id)
        assert job.status is JobStatus.CANCELLED
        assert stage_statuses(runner, job_id)["transcribe"] is StageStatus.CANCELLED
        # A cancelled job can be resumed from the cancelled stage.
        block.set()
        runner.resume(job_id)
        await wait_status(runner, job_id, JobStatus.WAITING_FOR_INPUT)
        assert log.names() == ["ingest", "transcribe", "diarize"]
    finally:
        block.set()
        await runner.stop()


async def test_cancel_waiting_and_queued_jobs(tmp_path: Path) -> None:
    runner = make_runner(tmp_path, standard_stages(Log()))
    await runner.start(prune=False)
    try:
        job_id = add_job(runner)
        await wait_status(runner, job_id, JobStatus.WAITING_FOR_INPUT)
        assert (await runner.cancel(job_id)).status is JobStatus.CANCELLED
        stages = stage_statuses(runner, job_id)
        assert stages["await_speaker_confirmation"] is StageStatus.CANCELLED
        with pytest.raises(MM3Error):
            await runner.cancel(job_id)  # already cancelled
    finally:
        await runner.stop()

    # Queued (runner not started): cancel straight away.
    runner = make_runner(tmp_path / "b", standard_stages(Log()))
    job_id = add_job(runner)
    assert (await runner.cancel(job_id)).status is JobStatus.CANCELLED


async def test_gpu_stages_never_overlap_between_jobs(tmp_path: Path) -> None:
    log = Log()
    settings = Settings()
    settings.jobs.max_concurrent = 3
    runner = make_runner(tmp_path, standard_stages(log, seconds=0.15), settings)
    await runner.start(prune=False)
    try:
        ids = [add_job(runner, f"J{i}") for i in range(3)]
        for job_id in ids:
            await wait_status(runner, job_id, JobStatus.WAITING_FOR_INPUT)
    finally:
        await runner.stop()
    # Each job's GPU block (transcribe+diarize) is held as one unit; blocks never overlap.
    blocks = []
    for job_id in ids:
        runs = [r for r in log.runs if r[1] == job_id and r[0] in {"transcribe", "diarize"}]
        blocks.append((min(r[2] for r in runs), max(r[3] for r in runs)))
    blocks.sort()
    for (_, end), (start, _) in itertools.pairwise(blocks):
        assert start >= end
    gpu = sorted((r[2], r[3]) for r in log.runs if r[0] in {"transcribe", "diarize"})
    for (_, end), (start, _) in itertools.pairwise(gpu):
        assert start >= end


async def test_retry_hook_retries_and_persists_options(tmp_path: Path) -> None:
    log = Log()
    stages = standard_stages(log)
    stages[1] = RecStage("transcribe", log, gpu=True, fail=1, retries=1)
    runner = make_runner(tmp_path, stages)
    await runner.start(prune=False)
    try:
        job_id = add_job(runner)
        await wait_status(runner, job_id, JobStatus.WAITING_FOR_INPUT)
        assert log.names()[:3] == ["ingest", "transcribe!", "transcribe"]
        assert runner.jobs.get(job_id).settings["batch_size"] == 4
        assert runner.stages.get(job_id, "transcribe").attempt == 2
    finally:
        await runner.stop()


async def test_failure_then_resume_with_overrides(tmp_path: Path) -> None:
    log = Log()
    stages = standard_stages(log)
    stages[1] = RecStage("transcribe", log, gpu=True, fail=1)
    runner = make_runner(tmp_path, stages)
    await runner.start(prune=False)
    try:
        job_id = add_job(runner)
        await wait_status(runner, job_id, JobStatus.FAILED)
        job = runner.jobs.get(job_id)
        assert job.error_code == "E_STAGE_FAILED" and "boom" in (job.error_message or "")
        rec = runner.stages.get(job_id, "transcribe")
        assert rec.status is StageStatus.FAILED and rec.detail["error"]["error_code"]
        runner.resume(job_id, {"model": "medium"})
        await wait_status(runner, job_id, JobStatus.WAITING_FOR_INPUT)
        job = runner.jobs.get(job_id)
        assert job.settings["model"] == "medium" and job.error_code is None
        assert log.names() == ["ingest", "transcribe!", "transcribe", "diarize"]
        with pytest.raises(MM3Error) as invalid:
            await runner.cancel(job_id)
            runner.resume(job_id, {"min_speakers": 0})
        assert invalid.value.code == "E_OPTIONS_INVALID"
    finally:
        await runner.stop()


async def test_mm3_error_code_is_kept(tmp_path: Path) -> None:
    class Oom(RecStage):
        def run(self, ctx: StageContext) -> Path:
            raise MM3Error("E_OOM", "Out of GPU memory.", "Try a smaller model.")

    log = Log()
    stages = standard_stages(log)
    stages[1] = Oom("transcribe", log, gpu=True)
    runner = make_runner(tmp_path, stages)
    await runner.start(prune=False)
    try:
        job_id = add_job(runner)
        await wait_status(runner, job_id, JobStatus.FAILED)
        assert runner.describe(job_id)["error"] == {
            "code": "E_OOM",
            "message": "Out of GPU memory.",
            "hint": "Try a smaller model.",
        }
    finally:
        await runner.stop()


async def test_artifact_outside_job_folder_fails(tmp_path: Path) -> None:
    class Escaping(RecStage):
        def run(self, ctx: StageContext) -> Path:
            outside = tmp_path / "outside.json"
            outside.write_text("{}")
            return outside

    log = Log()
    stages = standard_stages(log)
    stages[0] = Escaping("ingest", log)
    runner = make_runner(tmp_path, stages)
    await runner.start(prune=False)
    try:
        job_id = add_job(runner)
        await wait_status(runner, job_id, JobStatus.FAILED)
        assert runner.jobs.get(job_id).error_code == "E_STAGE_ARTIFACT"
    finally:
        await runner.stop()


async def test_input_required_from_any_stage(tmp_path: Path) -> None:
    """Phase 06's language gate raises InputRequired from a normal stage."""

    class Gate(RecStage):
        def run(self, ctx: StageContext) -> Path:
            answer = ctx.input()
            if answer is None:
                raise InputRequired("language", {"detected": "de"})
            return ctx.write_json("gate.json", answer)

    log = Log()
    stages = standard_stages(log)
    stages.insert(2, Gate("language_gate", log))
    runner = make_runner(tmp_path, stages)
    await runner.start(prune=False)
    try:
        job_id = add_job(runner)
        await wait_status(runner, job_id, JobStatus.WAITING_FOR_INPUT)
        assert runner.describe(job_id)["waiting_for"] == {
            "kind": "language",
            "stage": "language_gate",
            "detected": "de",
        }
        runner.submit_input(job_id, {"proceed": True})
        await wait_status(runner, job_id, JobStatus.WAITING_FOR_INPUT)
        assert runner.describe(job_id)["waiting_for"]["kind"] == "speaker_confirmation"
    finally:
        await runner.stop()


async def test_shutdown_marks_running_job_interrupted(tmp_path: Path) -> None:
    log = Log()
    block = threading.Event()
    stages = standard_stages(log)
    stages[1] = RecStage("transcribe", log, gpu=True, block=block)
    runner = make_runner(tmp_path, stages)
    await runner.start(prune=False)
    job_id = add_job(runner)
    await asyncio.to_thread(stages[1].entered.wait, 5)  # type: ignore[attr-defined]
    await runner.stop()
    job = runner.jobs.get(job_id)
    assert job.status is JobStatus.INTERRUPTED and job.error_code == "E_INTERRUPTED"
    assert stage_statuses(runner, job_id)["transcribe"] is StageStatus.INTERRUPTED


async def test_queued_jobs_are_requeued_on_start(tmp_path: Path) -> None:
    log = Log()
    runner = make_runner(tmp_path, standard_stages(log))
    job_id = add_job(runner)  # queued while the runner is not running
    await runner.start(prune=False)
    try:
        await wait_status(runner, job_id, JobStatus.WAITING_FOR_INPUT)
    finally:
        await runner.stop()


async def test_delete_and_pin(tmp_path: Path) -> None:
    runner = make_runner(tmp_path, standard_stages(Log()))
    await runner.start(prune=False)
    try:
        job_id = add_job(runner)
        await wait_status(runner, job_id, JobStatus.WAITING_FOR_INPUT)
        runner.set_pinned(job_id, True)
        with pytest.raises(MM3Error) as pinned:
            runner.delete(job_id)
        assert pinned.value.code == "E_JOB_PINNED"
        runner.delete(job_id, force=True)
        assert not job_dir(runner.jobs_root, job_id).exists()
        assert runner.jobs.find(job_id) is None

        block = threading.Event()
        other = add_job(runner)
        with pytest.raises(MM3Error) as active:
            runner.delete(other)
        assert active.value.code == "E_JOB_ACTIVE"
        block.set()
    finally:
        await runner.stop()


async def test_resume_and_cancel_reject_wrong_states(tmp_path: Path) -> None:
    runner = make_runner(tmp_path, standard_stages(Log()))
    await runner.start(prune=False)
    try:
        job_id = add_job(runner)
        await wait_status(runner, job_id, JobStatus.WAITING_FOR_INPUT)
        with pytest.raises(MM3Error) as e:
            runner.resume(job_id)
        assert e.value.status_code == 409
    finally:
        await runner.stop()


async def test_progress_events_carry_eta_and_order(tmp_path: Path) -> None:
    log = Log()
    runner = make_runner(tmp_path, standard_stages(log, seconds=0.0))
    await runner.start(prune=False)
    events = []
    try:
        job_id = add_job(runner)
        async with runner.bus.subscribe(job_id) as q:
            await wait_status(runner, job_id, JobStatus.WAITING_FOR_INPUT)
            await asyncio.sleep(0.05)
            while not q.empty():
                events.append(q.get_nowait())
    finally:
        await runner.stop()
    seqs = [e.seq for e in events]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    completed = [e.stage for e in events if e.status == "completed"]
    assert completed == ["ingest", "transcribe", "diarize"]
    assert events[-1].kind == "job" and events[-1].status == "waiting_for_input"
