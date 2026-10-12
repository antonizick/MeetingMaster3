"""Export API: a meeting's note and transcript (as files, a zip or plain text) and all app data."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import Response

from meetingmaster3 import exporting
from meetingmaster3.errors import MM3Error
from meetingmaster3.jobs.files import check_job_id, job_dir
from meetingmaster3.templates.stages import WRITTEN_FILE
from meetingmaster3.vault.io import read_text
from meetingmaster3.vault.paths import resolve_vault_root
from meetingmaster3.web.api.jobs import get_runner

router = APIRouter(tags=["export"])


def _download(data: bytes | str, filename: str, media_type: str) -> Response:
    ascii_name = filename.encode("ascii", "replace").decode().replace("?", "_").replace('"', "")
    return Response(
        data,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{ascii_name}"; '
            f"filename*=UTF-8''{quote(filename)}"
        },
    )


def _kind(kind: str) -> str:
    if kind not in exporting.KINDS:
        raise MM3Error(
            "E_BODY_INVALID",
            f"Unknown export kind {kind!r}.",
            f"Use one of: {', '.join(exporting.KINDS)}.",
            status_code=422,
        )
    return kind


def build_export(
    vault_root: Path, note_relative: str, kind: str, audio: Path | None
) -> tuple[bytes | str, str, str]:
    """``(content, filename, media type)`` for one meeting."""
    note, transcript = exporting.locate(vault_root, note_relative)
    stem = exporting.safe_filename(note.stem)
    if kind == "note":
        return read_text(note), f"{stem}.md", "text/markdown; charset=utf-8"
    if kind == "zip":
        data = exporting.meeting_zip(note, transcript, audio, audio_name=f"{stem}.opus")
        return data, f"{stem}.zip", "application/zip"
    if transcript is None:
        raise MM3Error(
            "E_TRANSCRIPT_MISSING",
            "This meeting has no companion transcript.",
            "It was written with generation.write_companion turned off.",
            status_code=404,
        )
    text = read_text(transcript)
    if kind == "transcript":
        return text, f"{stem}.transcript.md", "text/markdown; charset=utf-8"
    return exporting.transcript_to_text(text), f"{stem}.txt", "text/plain; charset=utf-8"


@router.get("/api/export/meeting")
async def export_note(request: Request, note: str, kind: str = "zip") -> Response:
    """Export by vault-relative note path (no audio: pass through a job for that)."""
    root = resolve_vault_root(request.app.state.settings.vault.path)
    content, name, media = await asyncio.to_thread(build_export, root, note, _kind(kind), None)
    return _download(content, name, media)


@router.get("/api/jobs/{job_id}/export")
async def export_job(request: Request, job_id: str, kind: str = "zip") -> Response:
    """Export the meeting a job wrote; the zip includes the audio while it is retained."""
    runner = get_runner(request)
    check_job_id(job_id)
    written_file = job_dir(runner.jobs_root, job_id) / WRITTEN_FILE
    written: dict[str, Any] = {}
    if written_file.is_file():
        written = json.loads(written_file.read_text(encoding="utf-8"))
    relative = written.get("note_relative")
    if not relative:
        raise MM3Error(
            "E_NOTE_NOT_FOUND",
            "This job has not written a note yet.",
            "Export is available once the note is written to the vault.",
            status_code=404,
        )
    audio: Path | None = None
    if _kind(kind) == "zip":
        try:
            audio = runner.audio_file(job_id)
        except MM3Error:
            audio = None  # expired or missing audio: the zip simply has no audio
    root = resolve_vault_root(request.app.state.settings.vault.path)
    content, name, media = await asyncio.to_thread(build_export, root, relative, kind, audio)
    return _download(content, name, media)


@router.get("/api/export/all")
async def export_everything(request: Request) -> Response:
    """Every table, the masked settings and the job artifacts as one zip (no secrets)."""
    runner = get_runner(request)
    data = await asyncio.to_thread(
        exporting.export_all, runner.db, request.app.state.settings, runner.jobs_root
    )
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%d-%H%M%S")
    return _download(data, f"mm3-export-{stamp}.zip", "application/zip")
