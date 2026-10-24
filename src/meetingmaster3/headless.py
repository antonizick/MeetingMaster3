"""Headless processing: audio file → note in the vault, without the web UI (``mm3 process``), and
a transcript or AI conversation → note (``mm3 import``, Phase 15k).

Drives a :class:`~meetingmaster3.jobs.runner.JobRunner` in its own event loop and answers the
job's questions from arguments (``--speakers``, ``--cloud-consent``) or, on a terminal, by
asking. Everything goes through the same job pipeline as the web app.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import json
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from meetingmaster3.config.paths import AppPaths
from meetingmaster3.config.settings import Settings
from meetingmaster3.domain.filenames import parse_filename
from meetingmaster3.errors import MM3Error
from meetingmaster3.jobs.models import FINAL, JobOptions, JobStatus, ProgressEvent

E_INPUT_NEEDED = "E_INPUT_NEEDED"


def parse_speakers(text: str | None) -> dict[str, str]:
    """``"SPEAKER_00=Alice, SPEAKER_01=Bob"`` → ``{"SPEAKER_00": "Alice", ...}``."""
    out: dict[str, str] = {}
    for part in (text or "").split(","):
        if not part.strip():
            continue
        label, sep, name = part.partition("=")
        if not sep or not label.strip() or not name.strip():
            raise MM3Error(
                "E_SPEAKERS_INVALID",
                f"Cannot read the speaker mapping {part.strip()!r}.",
                'Use --speakers "SPEAKER_00=Alice,SPEAKER_01=Bob".',
            )
        out[label.strip()] = name.strip()
    return out


Ask = Callable[[str, dict[str, Any]], dict[str, Any] | None]
"""(question kind, payload) → answer, or None when it cannot be answered."""
Echo = Callable[[str], None]


@dataclass
class ProcessRequest:
    audio: Path
    """The recording, or for an ``import`` the text file."""
    options: JobOptions
    speakers: dict[str, str] | None = None
    cloud_consent: bool = False
    job_type: str = "meeting"
    share: bool = False
    """An ``import`` of a Grok share link: ``options.import_share_id`` is downloaded by the job
    and ``audio`` is not read (Phase 15l)."""


@dataclass
class ProcessResult:
    job_id: str
    status: JobStatus
    written: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)


def build_options(
    audio: Path, *, title: str | None, date: dt.date | None, **extra: Any
) -> JobOptions:
    """Job options, with the title and date guessed from the file name when not given."""
    guess = parse_filename(audio.name)
    data: dict[str, Any] = {k: v for k, v in extra.items() if v not in (None, [], "")}
    data["title"] = title or guess.title or audio.stem
    meeting_date = date or guess.date
    if meeting_date:
        data["meeting_date"] = meeting_date.isoformat()
    if "meeting_time" not in data and guess.time is not None:
        data["meeting_time"] = guess.time.isoformat()
    try:
        return JobOptions.model_validate(data)
    except ValueError as exc:
        raise MM3Error("E_OPTIONS_INVALID", f"Invalid options: {exc}", "") from exc


def build_import_options(
    path: Path,
    data: bytes,
    settings: Settings,
    *,
    title: str | None,
    date: dt.date | None,
    **extra: Any,
) -> JobOptions:
    """Job options for ``mm3 import``: the title and date from the arguments, else from the file
    itself (its heading or frontmatter), else from the file name."""
    from meetingmaster3.importing.stages import import_defaults, parse_upload

    found = import_defaults(parse_upload(data, path.name, settings))
    title = title or found.get("title")
    if date is None and found.get("meeting_date"):
        date = dt.date.fromisoformat(found["meeting_date"])
    if "meeting_time" in found and not extra.get("meeting_time"):
        extra["meeting_time"] = dt.time.fromisoformat(found["meeting_time"])
    return build_options(path, title=title, date=date, **extra)


def build_share_options(
    link: str, *, title: str | None, date: dt.date | None, **extra: Any
) -> JobOptions:
    """Job options for ``mm3 import <share link>``: the link is checked here (no request is
    made for an unsupported one); details left out are filled from the downloaded conversation."""
    from meetingmaster3.importing.grok_share import parse_share_url
    from meetingmaster3.importing.stages import share_options

    data: dict[str, Any] = {k: v for k, v in extra.items() if v not in (None, [], "")}
    if title:
        data["title"] = title
    if date:
        data["meeting_date"] = date.isoformat()
    try:
        return JobOptions.model_validate(share_options(data, parse_share_url(link)))
    except ValueError as exc:
        raise MM3Error("E_OPTIONS_INVALID", f"Invalid options: {exc}", "") from exc


def answer_for(
    kind: str, payload: dict[str, Any], request: ProcessRequest, ask: Ask | None
) -> dict[str, Any]:
    """The answer to a job question, from the request or (if allowed) the terminal."""
    if kind == "speaker_confirmation" and request.speakers is not None:
        return {"speakers": dict(request.speakers)}
    if kind == "import_confirmation" and request.speakers is not None:
        return {"speakers": dict(request.speakers), "turns": {}}
    if kind == "cloud_consent" and request.cloud_consent:
        return {"consent": True}
    answer = ask(kind, payload) if ask is not None else None
    if answer is not None:
        return answer
    hints = {
        "speaker_confirmation": 'Pass --speakers "SPEAKER_00=Alice,SPEAKER_01=Bob".',
        "import_confirmation": "Pass --yes to accept the speakers as detected (name them with "
        "--speaker user=Nick --speaker assistant=Grok), or check them in the web app.",
        "cloud_consent": "Pass --cloud-consent to allow sending the transcript to the cloud "
        "backend, or choose a local backend.",
        "language": "Set transcription.on_non_english to 'proceed' or 'abort'.",
    }
    raise MM3Error(
        E_INPUT_NEEDED,
        f"The job needs an answer ({kind}) and there is no terminal to ask.",
        hints.get(kind, "Answer it in the web app."),
    )


async def process(
    settings: Settings,
    paths: AppPaths,
    request: ProcessRequest,
    *,
    ask: Ask | None = None,
    echo: Echo = print,
    pipeline_factory: Any = None,
) -> ProcessResult:
    """Run one recording through the full pipeline and return the outcome."""
    from meetingmaster3.audio.ingest import probe, safe_extension
    from meetingmaster3.importing.stages import (
        SHARE_SOURCE_NAME,
        import_duration,
        parse_upload,
        stored_name,
    )
    from meetingmaster3.jobs.files import job_dir, new_job_id, remove_job_dir
    from meetingmaster3.jobs.runner import JobRunner
    from meetingmaster3.llm.registry import BackendRegistry
    from meetingmaster3.storage.db import Database
    from meetingmaster3.templates.model_check import preflight

    importing = request.job_type == "import"
    if not request.share and not request.audio.is_file():
        what = "file" if importing else "audio file"
        raise MM3Error("E_AUDIO_MISSING", f"No {what} at {str(request.audio)!r}.", "")
    await preflight(
        BackendRegistry(settings), settings, request.options.backend, request.options.model
    )
    paths.ensure()
    db = Database.open(paths.database)
    kwargs: dict[str, Any] = {}
    if pipeline_factory is not None:
        kwargs["pipeline_factory"] = pipeline_factory
    runner = JobRunner(db, settings, paths, **kwargs)
    await runner.start(prune=False)
    job_id = new_job_id()
    try:
        folder = job_dir(runner.jobs_root, job_id, create=True)
        source_name = SHARE_SOURCE_NAME if request.share else request.audio.name
        if importing:
            name = stored_name(request.audio.name)
        else:
            name = f"original.{safe_extension(request.audio.name)}"
        if not request.share:
            await asyncio.to_thread(shutil.copyfile, request.audio, folder / name)
        try:
            if request.share:
                duration, audio_name = None, None
            elif importing:
                data = await asyncio.to_thread((folder / name).read_bytes)
                conv = parse_upload(data, request.audio.name, settings)
                duration, audio_name = import_duration(conv), None
            else:
                info = await asyncio.to_thread(probe, folder / name)
                duration, audio_name = info.duration_seconds, name
        except BaseException:
            remove_job_dir(runner.jobs_root, job_id)
            raise
        async with runner.bus.subscribe(job_id) as queue:
            runner.create_job(
                job_id,
                options=request.options,
                source_filename=source_name,
                audio_name=audio_name,
                duration_seconds=duration,
                job_type=request.job_type,
            )
            echo(f"Job {job_id}: {request.options.title}")
            await _follow(runner, job_id, queue, request, ask, echo)
        job = runner.describe(job_id)
        result = ProcessResult(
            job_id,
            JobStatus(job["status"]),
            error=job.get("error") if job["status"] != JobStatus.WRITTEN else None,
            warnings=[w["message"] for w in job.get("warnings", [])],
        )
        written = folder / "written.json"
        if result.status is JobStatus.WRITTEN and written.is_file():
            result.written = json.loads(written.read_text(encoding="utf-8"))
        return result
    except (asyncio.CancelledError, KeyboardInterrupt):
        with contextlib.suppress(Exception):
            await runner.cancel(job_id)
        raise
    finally:
        await runner.stop()
        db.close()


async def _follow(
    runner: Any,
    job_id: str,
    queue: asyncio.Queue[ProgressEvent],
    request: ProcessRequest,
    ask: Ask | None,
    echo: Echo,
) -> None:
    last: dict[str, str] = {}
    while True:
        event = await queue.get()
        if event.kind == "stage" and event.stage:
            pct = f" {event.fraction * 100:3.0f}%" if event.fraction is not None else ""
            line = f"  {event.stage}: {event.status}{pct} {event.message}".rstrip()
            if event.status in {"completed", "failed"} or last.get(event.stage) != event.message:
                echo(line)
                last[event.stage] = event.message
            continue
        status = JobStatus(event.status)
        if status is JobStatus.WAITING_FOR_INPUT:
            question = dict(event.data.get("input") or {})
            kind = str(question.pop("kind", ""))
            try:
                answer = answer_for(kind, question, request, ask)
            except MM3Error:
                await runner.cancel(job_id)
                raise
            runner.submit_input(job_id, answer)
        elif status in FINAL:
            return
