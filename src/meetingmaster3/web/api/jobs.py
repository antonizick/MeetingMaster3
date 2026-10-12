"""Jobs API: upload, list, inspect, cancel, resume, answer input, delete, pin, audio, SSE.

State-changing routes are POST/DELETE and therefore pass the CSRF middleware (S2).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import ValidationError
from python_multipart.multipart import MultipartParser, parse_options_header

from meetingmaster3.audio.ingest import (
    UploadTooLarge,
    display_filename,
    probe,
    safe_extension,
    save_stream,
)
from meetingmaster3.domain.filenames import parse_filename
from meetingmaster3.errors import MM3Error
from meetingmaster3.jobs.files import check_job_id, job_dir, new_job_id, remove_job_dir
from meetingmaster3.jobs.models import FINAL, JobOptions, JobStatus, ProgressEvent
from meetingmaster3.jobs.runner import JobRunner
from meetingmaster3.templates.model_check import preflight

router = APIRouter(prefix="/api/jobs")

HEARTBEAT_SECONDS = 15.0
MAX_OPTIONS_BYTES = 64 * 1024
UPLOAD_SLACK_BYTES = 1024 * 1024  # multipart framing and the options field


def get_runner(request: Request) -> JobRunner:
    runner: JobRunner | None = getattr(request.app.state, "runner", None)
    if runner is None or not runner.started:
        raise MM3Error(
            "E_RUNNER_DOWN",
            "The job runner is not running.",
            "Restart MeetingMaster3 with `mm3 serve`.",
            status_code=503,
        )
    return runner


def _bad_upload(message: str) -> MM3Error:
    return MM3Error(
        "E_UPLOAD_INVALID",
        message,
        'Send multipart/form-data with a "file" part and an optional JSON "options" part.',
        status_code=400,
    )


class _MultipartUpload:
    """Streams a multipart body: the ``file`` part goes straight to disk, the ``options`` part
    is kept in memory (bounded). Other parts are ignored."""

    def __init__(self, boundary: bytes) -> None:
        self.options = b""
        self.filename: str | None = None
        self.file_parts = 0
        self._headers: dict[bytes, bytes] = {}
        self._field = b""
        self._value = b""
        self._part: str | None = None
        self._pending: list[bytes] = []
        self.parser = MultipartParser(
            boundary,
            {
                "on_part_begin": self._part_begin,
                "on_header_field": self._header_field,
                "on_header_value": self._header_value,
                "on_header_end": self._header_end,
                "on_headers_finished": self._headers_finished,
                "on_part_data": self._part_data,
                "on_part_end": self._part_end,
            },
        )

    def _part_begin(self) -> None:
        self._headers, self._part = {}, None

    def _header_field(self, data: bytes, start: int, end: int) -> None:
        self._field += data[start:end]

    def _header_value(self, data: bytes, start: int, end: int) -> None:
        self._value += data[start:end]

    def _header_end(self) -> None:
        self._headers[self._field.lower()] = self._value
        self._field, self._value = b"", b""

    def _headers_finished(self) -> None:
        _, params = parse_options_header(self._headers.get(b"content-disposition", b""))
        name = params.get(b"name", b"").decode("utf-8", "replace")
        if name == "file":
            if self.file_parts:
                raise _bad_upload("Only one file can be uploaded per job.")
            self.file_parts += 1
            self.filename = params.get(b"filename", b"").decode("utf-8", "replace")
            self._part = "file"
        elif name == "options":
            self._part = "options"

    def _part_data(self, data: bytes, start: int, end: int) -> None:
        if self._part == "file":
            self._pending.append(bytes(data[start:end]))
        elif self._part == "options":
            self.options += data[start:end]
            if len(self.options) > MAX_OPTIONS_BYTES:
                raise _bad_upload("The options field is too large.")

    def _part_end(self) -> None:
        self._part = None

    def take(self) -> list[bytes]:
        chunks, self._pending = self._pending, []
        return chunks


async def _receive_upload(
    request: Request, runner: JobRunner, job_id: str
) -> tuple[_MultipartUpload, str, int]:
    content_type, params = parse_options_header(request.headers.get("content-type", ""))
    boundary = params.get(b"boundary")
    if content_type != b"multipart/form-data" or not boundary:
        raise _bad_upload("The upload must be multipart/form-data.")
    max_bytes = runner.settings.audio.max_upload_mb * 1024 * 1024
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > max_bytes + UPLOAD_SLACK_BYTES:
        raise UploadTooLarge(max_bytes)

    upload = _MultipartUpload(boundary)
    folder = job_dir(runner.jobs_root, job_id, create=True)
    tmp = folder / ".upload.part"

    async def file_chunks() -> AsyncIterator[bytes]:
        async for chunk in request.stream():
            upload.parser.write(chunk)
            for piece in upload.take():
                yield piece
        upload.parser.finalize()
        for piece in upload.take():
            yield piece

    size = await save_stream(file_chunks(), tmp, max_bytes)
    if not upload.file_parts:
        tmp.unlink(missing_ok=True)
        raise _bad_upload('No "file" part in the upload.')
    if size == 0:
        tmp.unlink(missing_ok=True)
        raise _bad_upload("The uploaded file is empty.")
    name = f"original.{safe_extension(upload.filename)}"
    tmp.rename(folder / name)
    return upload, name, size


def _parse_options(raw: bytes, filename: str) -> JobOptions:
    try:
        data: Any = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as exc:
        raise _bad_upload("The options field is not valid JSON.") from exc
    if not isinstance(data, dict):
        raise _bad_upload("The options field must be a JSON object.")
    guess = parse_filename(filename)
    if not data.get("title") and guess.title:
        data["title"] = guess.title
    if not data.get("meeting_date") and guess.date:
        data["meeting_date"] = guess.date.isoformat()
    try:
        return JobOptions.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first.get("loc", ()))
        raise MM3Error(
            "E_OPTIONS_INVALID",
            f"Invalid option {where!r}: {first.get('msg', 'invalid value')}.",
            "Check the option names and values.",
            status_code=422,
        ) from exc


@router.post("", status_code=201)
async def create_job(request: Request) -> dict[str, Any]:
    """Upload audio (multipart ``file``) with JSON ``options``; returns the queued job."""
    runner = get_runner(request)
    job_id = new_job_id()
    try:
        upload, audio_name, _ = await _receive_upload(request, runner, job_id)
        folder = job_dir(runner.jobs_root, job_id)
        filename = display_filename(upload.filename)
        options = _parse_options(upload.options, filename)
        await preflight(
            request.app.state.llm_registry, runner.settings, options.backend, options.model
        )
        info = await asyncio.to_thread(probe, folder / audio_name)
        runner.create_job(
            job_id,
            options=options,
            source_filename=filename,
            audio_name=audio_name,
            duration_seconds=info.duration_seconds,
        )
    except BaseException:
        with contextlib.suppress(Exception):
            if runner.jobs.find(job_id) is None:
                remove_job_dir(runner.jobs_root, job_id)
        raise
    return runner.describe(job_id)


@router.get("")
async def list_jobs(
    request: Request,
    status: list[JobStatus] | None = Query(default=None),  # noqa: B008
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    runner = get_runner(request)
    jobs = runner.jobs.list_jobs(set(status) if status else None, limit=limit, offset=offset)
    return {"jobs": [j.to_dict() for j in jobs]}


@router.get("/{job_id}")
async def get_job(request: Request, job_id: str) -> dict[str, Any]:
    return get_runner(request).describe(check_job_id(job_id))


@router.post("/{job_id}/cancel")
async def cancel_job(request: Request, job_id: str) -> dict[str, Any]:
    runner = get_runner(request)
    await runner.cancel(check_job_id(job_id))
    return runner.describe(job_id)


async def _json_body(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MM3Error("E_BODY_INVALID", "The request body is not valid JSON.", "") from exc
    if not isinstance(data, dict):
        raise MM3Error("E_BODY_INVALID", "The request body must be a JSON object.", "")
    return data


@router.post("/{job_id}/resume")
async def resume_job(request: Request, job_id: str) -> dict[str, Any]:
    """Resume from the first incomplete stage. Optional body ``{"overrides": {...}}``."""
    runner = get_runner(request)
    body = await _json_body(request)
    overrides = body.get("overrides") or {}
    if not isinstance(overrides, dict):
        raise MM3Error("E_BODY_INVALID", '"overrides" must be an object.', "")
    runner.resume(check_job_id(job_id), overrides)
    return runner.describe(job_id)


@router.post("/{job_id}/input")
async def submit_input(request: Request, job_id: str) -> dict[str, Any]:
    """Answer the question of a ``waiting_for_input`` job (e.g. the speaker mapping)."""
    runner = get_runner(request)
    runner.submit_input(check_job_id(job_id), await _json_body(request))
    return runner.describe(job_id)


@router.delete("/{job_id}")
async def delete_job(request: Request, job_id: str, force: bool = False) -> dict[str, Any]:
    get_runner(request).delete(check_job_id(job_id), force=force)
    return {"deleted": job_id}


@router.post("/{job_id}/pin")
async def pin_job(request: Request, job_id: str) -> dict[str, Any]:
    return get_runner(request).set_pinned(check_job_id(job_id), True).to_dict()


@router.post("/{job_id}/unpin")
async def unpin_job(request: Request, job_id: str) -> dict[str, Any]:
    return get_runner(request).set_pinned(check_job_id(job_id), False).to_dict()


_MEDIA_TYPES = {".opus": "audio/ogg", ".wav": "audio/wav", ".mp3": "audio/mpeg"}


@router.get("/{job_id}/audio")
async def job_audio(request: Request, job_id: str) -> FileResponse:
    """The job's audio, with HTTP Range support (``E_AUDIO_EXPIRED`` once pruned)."""
    path = get_runner(request).audio_file(check_job_id(job_id))
    return FileResponse(
        path,
        media_type=_MEDIA_TYPES.get(path.suffix, "application/octet-stream"),
        headers={"Cache-Control": "no-store"},
    )


def _sse(event: str, data: dict[str, Any], seq: int | None = None) -> str:
    head = f"id: {seq}\n" if seq is not None else ""
    return f"{head}event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@router.get("/{job_id}/events")
async def job_events(request: Request, job_id: str) -> StreamingResponse:
    """Server-sent events: one ``snapshot`` with the current state, then ``stage`` and ``job``
    events as they happen, with a comment heartbeat. The stream ends after the job is written,
    failed or cancelled."""
    runner = get_runner(request)
    check_job_id(job_id)
    runner.jobs.get(job_id)  # 404 before the stream starts

    async def stream() -> AsyncIterator[str]:
        async with runner.bus.subscribe(job_id) as queue:
            snapshot = runner.describe(job_id)
            seen = snapshot["seq"]
            yield _sse("snapshot", snapshot, seen)
            if JobStatus(snapshot["status"]) in FINAL:
                return
            while True:
                try:
                    event: ProgressEvent = await asyncio.wait_for(queue.get(), HEARTBEAT_SECONDS)
                except TimeoutError:
                    yield ": heartbeat\n\n"
                    continue
                if event.seq <= seen:
                    continue  # already reflected in the snapshot
                seen = event.seq
                yield _sse(event.kind, event.to_dict(), event.seq)
                if event.kind == "job" and event.status in {s.value for s in FINAL}:
                    return

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
