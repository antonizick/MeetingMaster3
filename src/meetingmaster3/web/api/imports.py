"""Imports API: ``POST /api/imports`` starts an ``import`` job from a text file (R32).

The request has the same shape as ``POST /api/jobs`` (multipart ``file`` plus JSON
``options``) and passes the same CSRF, Host and Origin checks, but the file is a transcript or an
AI conversation: it is streamed to ``source.<ext>`` under the import size limit
(``importing.max_mb``) and parsed once before the job is created, so an unreadable file is
refused at once instead of failing in the job. There is no ffprobe, audio or GPU step.

Instead of a file, ``options.share_url`` may hold a Grok share link (Phase 15l). The link is
checked here (an unsupported link is a 422 and no request is made); the job then downloads the
share in its ``import_parse`` stage.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any

from fastapi import APIRouter, Request

from meetingmaster3.audio.ingest import UploadTooLarge, display_filename
from meetingmaster3.errors import MM3Error
from meetingmaster3.importing.grok_share import parse_share_url, unsupported_link
from meetingmaster3.importing.model import too_large
from meetingmaster3.importing.stages import (
    SHARE_SOURCE_NAME,
    import_defaults,
    import_duration,
    parse_upload,
    share_options,
    stored_name,
)
from meetingmaster3.jobs.files import job_dir, new_job_id, remove_job_dir
from meetingmaster3.jobs.runner import JobRunner
from meetingmaster3.templates.model_check import preflight
from meetingmaster3.web.api.jobs import (
    _bad_upload,
    _parse_options,
    _receive_upload,
    _remember_template,
    get_runner,
)

router = APIRouter(prefix="/api/imports")

ACCEPT = ".md,.markdown,.txt,.vtt,.srt"
"""What the New meeting page's import file input accepts."""
SHARE_URL_OPTION = "share_url"


def _split_share_url(raw: bytes) -> tuple[bytes, str | None]:
    """The options without ``share_url``, and the link (``None`` when absent or empty)."""
    try:
        data: Any = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return raw, None  # _parse_options reports it
    if not isinstance(data, dict) or SHARE_URL_OPTION not in data:
        return raw, None
    link = data.pop(SHARE_URL_OPTION)
    if link is not None and not isinstance(link, str):
        raise unsupported_link()
    return json.dumps(data).encode(), (link or "").strip() or None


@router.post("", status_code=201)
async def create_import(request: Request) -> dict[str, Any]:
    """Upload a transcript or an AI conversation (multipart ``file``) with JSON ``options``, or
    send only ``options`` with a Grok ``share_url``; returns the queued ``import`` job."""
    runner = get_runner(request)
    settings = runner.settings
    job_id = new_job_id()
    try:
        try:
            upload, name, _ = await _receive_upload(
                request,
                runner,
                job_id,
                max_bytes=settings.importing.max_mb * 1024 * 1024,
                stored_name=stored_name,
                require_file=False,
            )
        except UploadTooLarge as exc:
            raise too_large(settings.importing.max_mb) from exc
        raw, link = _split_share_url(upload.options)
        if name and link:
            raise MM3Error(
                "E_UPLOAD_INVALID",
                "Choose a file or paste a share link, not both.",
                "Clear one of them and start again.",
                status_code=422,
            )
        if not name:
            if link is None:
                raise _bad_upload('No "file" part in the upload.')
            given = json.loads(raw) if raw.strip() else {}
            share = share_options(given, parse_share_url(link))
            options, remember = _parse_options(json.dumps(share).encode(), "")
            registry = request.app.state.llm_registry
            await preflight(registry, settings, options.backend, options.model)
            runner.create_job(
                job_id,
                options=options,
                source_filename=SHARE_SOURCE_NAME,
                audio_name=None,
                duration_seconds=None,
                job_type="import",
            )
            return await _created(request, runner, job_id, remember, options.template)
        filename = display_filename(upload.filename)
        path = job_dir(runner.jobs_root, job_id) / name
        data = await asyncio.to_thread(path.read_bytes)
        conv = await asyncio.to_thread(parse_upload, data, filename, settings)
        options, remember = _parse_options(raw, filename, defaults=import_defaults(conv))
        await preflight(request.app.state.llm_registry, settings, options.backend, options.model)
        runner.create_job(
            job_id,
            options=options,
            source_filename=filename,
            audio_name=None,
            duration_seconds=import_duration(conv),
            job_type="import",
        )
    except BaseException:
        with contextlib.suppress(Exception):
            if runner.jobs.find(job_id) is None:
                remove_job_dir(runner.jobs_root, job_id)
        raise
    return await _created(request, runner, job_id, remember, options.template)


async def _created(
    request: Request, runner: JobRunner, job_id: str, remember: bool, template: str | None
) -> dict[str, Any]:
    if remember and template:
        await _remember_template(request, template)
    return runner.describe(job_id)
