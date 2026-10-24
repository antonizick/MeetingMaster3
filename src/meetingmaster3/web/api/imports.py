"""Imports API: ``POST /api/imports`` starts an ``import`` job from a text file (R32).

The request has the same shape as ``POST /api/jobs`` (multipart ``file`` plus JSON
``options``) and passes the same CSRF, Host and Origin checks, but the file is a transcript or an
AI conversation: it is streamed to ``source.<ext>`` under the import size limit
(``importing.max_mb``) and parsed once before the job is created, so an unreadable file is
refused at once instead of failing in the job. There is no ffprobe, audio or GPU step.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from fastapi import APIRouter, Request

from meetingmaster3.audio.ingest import UploadTooLarge, display_filename
from meetingmaster3.importing.model import too_large
from meetingmaster3.importing.stages import (
    import_defaults,
    import_duration,
    parse_upload,
    stored_name,
)
from meetingmaster3.jobs.files import job_dir, new_job_id, remove_job_dir
from meetingmaster3.templates.model_check import preflight
from meetingmaster3.web.api.jobs import (
    _parse_options,
    _receive_upload,
    _remember_template,
    get_runner,
)

router = APIRouter(prefix="/api/imports")

ACCEPT = ".md,.markdown,.txt,.vtt,.srt"
"""What the New meeting page's import file input accepts."""


@router.post("", status_code=201)
async def create_import(request: Request) -> dict[str, Any]:
    """Upload a transcript or an AI conversation (multipart ``file``) with JSON ``options``;
    returns the queued ``import`` job."""
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
            )
        except UploadTooLarge as exc:
            raise too_large(settings.importing.max_mb) from exc
        filename = display_filename(upload.filename)
        path = job_dir(runner.jobs_root, job_id) / name
        data = await asyncio.to_thread(path.read_bytes)
        conv = await asyncio.to_thread(parse_upload, data, filename, settings)
        options, remember = _parse_options(upload.options, filename, defaults=import_defaults(conv))
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
    if remember and options.template:
        await _remember_template(request, options.template)
    return runner.describe(job_id)
