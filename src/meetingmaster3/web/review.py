"""The review workspace (Phase 11): re-open, edit, regenerate, switch template, rename speakers.

Pages are server-rendered; the workspace's actions are JSON requests from
``static/js/review.js`` (the editor's state is a list of parts, not a form). Every action names
the note by its vault-relative ``path`` and is re-checked here: confined to the vault, still the
same meeting (``mm3-id``), not an archive. State-changing routes are POST/DELETE and pass the
CSRF middleware (S2). Rendered Markdown goes through ``web.render`` (S3).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import shutil
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from meetingmaster3.config.settings import Settings
from meetingmaster3.errors import MM3Error
from meetingmaster3.feedback.context import feedback_context
from meetingmaster3.feedback.store import FeedbackStore
from meetingmaster3.hardware.detect import get_hardware
from meetingmaster3.hardware.recommend import recommend
from meetingmaster3.jobs.files import job_dir, new_job_id
from meetingmaster3.jobs.models import JobOptions
from meetingmaster3.jobs.pipeline import fake_pipeline_enabled
from meetingmaster3.llm.registry import BackendRegistry
from meetingmaster3.markdown.diff import diff_stats, side_by_side, unified_diff
from meetingmaster3.markdown.editing import Edits, split_document
from meetingmaster3.markdown.frontmatter import wikilink
from meetingmaster3.markdown.note_parser import parse_note
from meetingmaster3.markdown.note_writer import render_note, with_transcript_link
from meetingmaster3.markdown.sections import (
    SectionMarkerError,
    append_section,
    parse_inner,
    render_inner,
    replace_section,
    scan_sections,
    section_inner,
)
from meetingmaster3.review import retention_view
from meetingmaster3.review.progress import (
    LongTask,
    TaskRegistry,
    TaskState,
    expected_seconds,
)
from meetingmaster3.review.rename import plan_rename
from meetingmaster3.review.retitle import apply_retitle, plan_retitle
from meetingmaster3.review.save import (
    SaveConflict,
    base_text,
    build_text,
    check_note,
    save_note,
    write_checked,
)
from meetingmaster3.review.store import ReviewStore, text_sha
from meetingmaster3.review.switch import switch_template
from meetingmaster3.review.workspace import (
    Workspace,
    check_mm3_id,
    clock,
    find_job,
    load_workspace,
    locate_note,
    not_found,
)
from meetingmaster3.speakers.cascade import save_job_speakers
from meetingmaster3.storage.repositories import RecentMeetingsRepository
from meetingmaster3.templates.regenerate import (
    E_TRANSCRIPT_MISSING,
    find_companion,
    regenerate_text,
    transcript_missing,
)
from meetingmaster3.templates.stages import template_library
from meetingmaster3.vault.archive import archive_note, archive_section
from meetingmaster3.vault.io import atomic_write_text, read_text
from meetingmaster3.vault.naming import NOTE_SUFFIX
from meetingmaster3.vault.paths import confine, resolve_vault_root
from meetingmaster3.vault.picker import browse, find_companions, read_identity
from meetingmaster3.vault.readable import readable_link, refresh_readable
from meetingmaster3.web import views
from meetingmaster3.web.api.jobs import get_runner
from meetingmaster3.web.ask_ui import answers_for_meeting
from meetingmaster3.web.pages import render, templates
from meetingmaster3.web.paging import page_params, picker_context, with_params
from meetingmaster3.web.render import render_markdown

router = APIRouter()
templates.env.filters["clock"] = clock


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def _root(request: Request) -> Path:
    return resolve_vault_root(_settings(request).vault.path)


def _recents(request: Request) -> RecentMeetingsRepository:
    return RecentMeetingsRepository(get_runner(request).db)


def _store(request: Request, mm3_id: str) -> ReviewStore:
    return ReviewStore(request.app.state.paths.data_dir, mm3_id)


def backend_lookup(request: Request) -> Any:
    """The LLM backends for regeneration: the app's registry, or the offline fake model when
    the server runs with ``MM3_FAKE_PIPELINE=1`` (like the fake pipeline's generate stage)."""
    if fake_pipeline_enabled():
        from meetingmaster3.jobs.fakes import fake_backend

        settings = _settings(request)
        return lambda name: fake_backend(settings, name)[1]
    registry: BackendRegistry = request.app.state.llm_registry
    return registry.get


def _fragment(request: Request, name: str, context: dict[str, Any]) -> str:
    template = templates.get_template(name)
    return template.render({"request": request, **context})


async def _body[M: BaseModel](request: Request, model: type[M]) -> M:
    from meetingmaster3.web.api.templates import _body as parse_body

    return await parse_body(request, model)


class NoteRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=4096)


def _locate(request: Request, mm3_id: str, rel: str) -> tuple[Path, Path]:
    root = _root(request)
    path, _ = locate_note(root, _recents(request), check_mm3_id(mm3_id), rel)
    return root, path


# -- re-open: picker and recent list --------------------------------------------------------------


@router.get("/open")
async def open_page(request: Request, dir: str = "") -> Response:
    """ "Open a note" was merged into the Meetings page (Phase 15c, R27); old links land there,
    with the folder picker on the same ``dir``."""
    return RedirectResponse(with_params("/meetings", {"dir": dir}), status_code=303)


@router.get("/ui/open/browse", response_class=HTMLResponse)
async def open_browse(request: Request, dir: str = "") -> HTMLResponse:
    params = page_params(request.query_params)
    listing = await asyncio.to_thread(browse, _root(request), dir)
    return render(request, "partials/picker.html", picker_context(listing, params))


@router.get("/open/note")
async def open_note(request: Request, path: str) -> Response:
    """Open a vault note by its relative path: MM3 notes go to the workspace (and the Meetings
    list), anything else to the read-only preview."""
    root = _root(request)
    note = confine(root, path)
    if note.suffix != NOTE_SUFFIX or not note.is_file():
        raise not_found("no such file")
    info = await asyncio.to_thread(read_identity, note)
    if info is None or info.is_transcript:
        return RedirectResponse(f"/preview?path={quote(str(note), safe='')}", status_code=303)
    if info.archived:
        raise MM3Error(
            "E_NOTE_ARCHIVED",
            "That file is an archived copy of an earlier version.",
            "Open the meeting's current note instead; archives are kept for reference.",
            status_code=409,
        )
    try:
        mm3_id = check_mm3_id(info.mm3_id)
    except MM3Error:
        return RedirectResponse(f"/preview?path={quote(str(note), safe='')}", status_code=303)
    rel = note.relative_to(root).as_posix()
    _recents(request).touch(str(note), mm3_id=mm3_id, title=info.title)
    return RedirectResponse(f"/meetings/{mm3_id}?path={quote(rel)}", status_code=303)


# -- the workspace page ---------------------------------------------------------------------------


def _backends(request: Request) -> list[dict[str, Any]]:
    from meetingmaster3.web.pages import _backend_choices

    registry: BackendRegistry = request.app.state.llm_registry
    return _backend_choices(registry)


def _draft_context(ws: Workspace, store: ReviewStore) -> dict[str, Any] | None:
    draft = store.draft()
    if draft is None:
        return None
    same_shape = len(draft.edits.texts) == len(ws.doc.texts) and set(draft.edits.sections) <= set(
        ws.doc.section_ids
    )
    if not same_shape:
        return {"usable": False, "saved_at": draft.saved_at.isoformat()}
    try:
        text = build_text(store, draft.base_sha, draft.edits, allow_marker_changes=True)
    except MM3Error:
        text = None
    if text == ws.text:
        store.clear_draft()
        return None
    return {
        "usable": True,
        "saved_at": draft.saved_at.isoformat(),
        "stale": draft.base_sha != ws.sha,
        **draft.to_dict(),
    }


def _recording_info(runner: Any, job_id: str | None, stem: str) -> dict[str, Any] | None:
    """Size, format and download link of the stored recording (Phase 15c, R27); ``None`` when
    there is nothing to show (no job, or the file is gone)."""
    if job_id is None:
        return None
    try:
        path = runner.audio_file(job_id)
        size = path.stat().st_size
    except (MM3Error, OSError):
        return None
    name = views.audio_download_name(stem, path.suffix)
    return {
        "size": views.format_size(size),
        "format": views.audio_format(path),
        "suffix": path.suffix,
        "name": name,
        "download_url": f"/api/jobs/{job_id}/audio?download=1&name={quote(stem, safe='')}",
    }


def _retention_view(runner: Any, job_id: str | None) -> retention_view.RetentionView | None:
    if job_id is None:
        return None
    job = runner.jobs.get(job_id)
    return retention_view.for_job(job, runner.retention_status(job), runner.settings.privacy)


class KeepBody(NoteRef):
    keep: bool


@router.post("/ui/review/{mm3_id}/keep")
async def keep_recording(request: Request, mm3_id: str) -> dict[str, Any]:
    """Keep the meeting's recording forever (the job's pin), or allow its deletion again."""
    body = await _body(request, KeepBody)
    _locate(request, mm3_id, body.path)
    runner = get_runner(request)
    job_id = find_job(runner, check_mm3_id(mm3_id), None)
    if job_id is None:
        raise MM3Error(
            "E_AUDIO_MISSING",
            "No recording is linked to this note.",
            "It was processed elsewhere, or its job was deleted.",
            status_code=404,
        )
    runner.set_pinned(job_id, body.keep)
    view = _retention_view(runner, job_id)
    html = _fragment(request, "partials/retention.html", {"retention": view})
    return {"html": html, "pinned": body.keep}


@router.get("/meetings/{mm3_id}", response_class=HTMLResponse)
async def workspace_page(request: Request, mm3_id: str, path: str | None = None) -> HTMLResponse:
    runner = get_runner(request)
    root = _root(request)
    mm3_id = check_mm3_id(mm3_id)
    recents = _recents(request)
    note, entry = locate_note(root, recents, mm3_id, path)
    store = _store(request, mm3_id)
    ws = await asyncio.to_thread(load_workspace, root, note, mm3_id, store, runner, entry)
    meta = ws.parsed.note.meta if ws.parsed else None
    recents.touch(
        str(note),
        transcript_path=str(ws.companion_path) if ws.companion_path else None,
        mm3_id=mm3_id,
        title=meta.title if meta else note.stem,
        date=meta.date.date() if meta and meta.date else None,
        job_id=ws.job_id,
    )
    library = await asyncio.to_thread(
        template_library, _settings(request), request.app.state.paths.data_dir
    )
    feedback = FeedbackStore(runner.db)

    def fb(section_id: str | None = None) -> dict[str, Any]:
        return feedback_context(
            feedback,
            mm3_id,
            template_id=meta.template_id if meta else None,
            backend=meta.backend if meta else None,
            model=meta.model if meta else None,
            section_id=section_id,
        )

    data = {
        "mm3_id": mm3_id,
        "path": ws.relative,
        "base_sha": ws.sha,
        "readonly": ws.readonly,
        "can_regenerate": ws.can_regenerate,
        "draft": None if ws.readonly else _draft_context(ws, store),
    }
    return render(
        request,
        "review.html",
        {
            "active": "recent",
            "ws": ws,
            "meta": meta,
            "title": meta.title if meta else note.stem,
            "rendered": render_markdown(ws.text, timestamps=True),
            "data": data,
            "audio_url": f"/api/jobs/{ws.job_id}/audio" if ws.audio == "ok" else None,
            "recording": _recording_info(runner, ws.job_id, note.stem)
            if ws.audio == "ok"
            else None,
            "retention": _retention_view(runner, ws.job_id) if ws.audio == "ok" else None,
            "obsidian_link": views.obsidian_link(str(note)),
            "cited_by": await asyncio.to_thread(answers_for_meeting, request, mm3_id),
            "templates_list": [e.to_dict() for e in library.listing() if e.valid],
            "backends": _backends(request),
            "note_backend": (meta.backend if meta else None)
            or _settings(request).llm.default_backend,
            "note_model": (meta.model if meta else None) or "",
            "draft": data["draft"],
            "fb_note": fb() if meta else None,
            "fb_sections": {s.id: fb(s.id) for s in ws.doc.sections} if meta else {},
            "export_note": quote(ws.relative, safe=""),
            "lf": lambda s: s.replace("\r\n", "\n"),
        },
    )


# -- editor: draft, preview, save -----------------------------------------------------------------


class EditsBody(NoteRef):
    base_sha: str = Field(min_length=64, max_length=64)
    edits: dict[str, Any]


class SaveBody(EditsBody):
    force_sha: str | None = Field(default=None, min_length=64, max_length=64)
    allow_marker_changes: bool = False


def _diff_context(old: str, new: str, *, old_label: str, new_label: str) -> dict[str, Any]:
    rows = side_by_side(old, new)
    stats = diff_stats(rows)
    return {
        "rows": rows,
        "unified": unified_diff(old, new, old_label=old_label, new_label=new_label).splitlines(),
        "stats": stats,
        "old_label": old_label,
        "new_label": new_label,
    }


@router.post("/ui/review/{mm3_id}/draft")
async def save_draft(request: Request, mm3_id: str) -> dict[str, Any]:
    body = await _body(request, EditsBody)
    _locate(request, mm3_id, body.path)
    draft = _store(request, mm3_id).save_draft(body.base_sha, Edits.from_dict(body.edits))
    return {"saved_at": draft.saved_at.isoformat()}


@router.delete("/ui/review/{mm3_id}/draft")
async def discard_draft(request: Request, mm3_id: str) -> dict[str, Any]:
    _store(request, check_mm3_id(mm3_id)).clear_draft()
    return {"ok": True}


@router.post("/ui/review/{mm3_id}/render")
async def render_preview(request: Request, mm3_id: str) -> dict[str, Any]:
    body = await _body(request, EditsBody)
    _locate(request, mm3_id, body.path)
    text = build_text(
        _store(request, mm3_id),
        body.base_sha,
        Edits.from_dict(body.edits),
        allow_marker_changes=True,
    )
    return {"html": str(render_markdown(text, timestamps=True))}


def _conflict(request: Request, exc: SaveConflict) -> JSONResponse:
    html = _fragment(
        request,
        "partials/diff.html",
        _diff_context(exc.theirs, exc.mine, old_label="in the vault", new_label="yours"),
    )
    return JSONResponse(
        {**exc.to_dict(), "conflict": {"theirs_sha": exc.theirs_sha, "html": html}},
        status_code=409,
    )


@router.post("/ui/review/{mm3_id}/save")
async def save(request: Request, mm3_id: str) -> Response:
    body = await _body(request, SaveBody)
    root, path = _locate(request, mm3_id, body.path)
    store = _store(request, mm3_id)
    try:
        result = await asyncio.to_thread(
            save_note,
            root,
            path,
            check_mm3_id(mm3_id),
            store,
            base_sha=body.base_sha,
            edits=Edits.from_dict(body.edits),
            force_sha=body.force_sha,
            allow_marker_changes=body.allow_marker_changes,
        )
    except SaveConflict as exc:
        return _conflict(request, exc)
    return JSONResponse(
        {
            "sha": result.sha,
            "written": result.written,
            "saved_at": dt.datetime.now().strftime("%H:%M"),
        }
    )


# -- per-section regeneration ---------------------------------------------------------------------


class RegenerateBody(NoteRef):
    base_sha: str = Field(min_length=64, max_length=64)
    section_id: str = Field(min_length=1, max_length=64)
    inner: str | None = Field(default=None, max_length=1_000_000)
    """The editor's current content of the section (unsaved edits included)."""
    instructions: str | None = Field(default=None, max_length=4000)
    backend: str | None = None
    model: str | None = None
    cloud_consent: bool = False
    append: bool = False


@router.post("/ui/review/{mm3_id}/regenerate")
async def regenerate(request: Request, mm3_id: str) -> dict[str, Any]:
    """Start writing a new body for one section; the result (a diff against the editor's current
    version) is fetched from ``task/{id}/result`` when the task is done. Nothing is written: the
    browser applies it on Accept (and asks the server to archive the old one)."""
    body = await _body(request, RegenerateBody)
    root, path = _locate(request, mm3_id, body.path)
    store = _store(request, mm3_id)
    text = base_text(store, body.base_sha)
    doc = split_document(text)
    if not body.append and body.inner is not None:
        if doc.section(body.section_id) is None:
            raise SectionMarkerError(
                body.section_id, scan_sections(text).errors_for(body.section_id)
            )
        text = build_text(
            store,
            body.base_sha,
            Edits(
                texts=[t.replace("\r\n", "\n") for t in doc.texts],
                sections={body.section_id: body.inner},
            ),
            allow_marker_changes=True,
        )
    settings = _settings(request)
    library = template_library(settings, request.app.state.paths.data_dir)
    lookup = backend_lookup(request)
    estimate = await _estimator(request)

    async def work(task: LongTask) -> dict[str, Any]:
        preview = await regenerate_text(
            settings,
            library,
            lookup,
            root=root,
            path=path,
            text=text,
            section_id=body.section_id,
            instructions=body.instructions,
            backend=body.backend or None,
            model=body.model or None,
            cloud_consent=body.cloud_consent,
            append=body.append,
            progress=task.update,
            on_context=lambda duration, local: setattr(
                task, "expected_s", estimate(duration, local)
            ),
        )
        return {
            "preview": preview,
            "text": text,
            "append": body.append,
            "section_id": body.section_id,
        }

    task = _tasks(request).start(
        check_mm3_id(mm3_id),
        "regenerate",
        work,
        {"section_id": body.section_id, "append": body.append},
    )
    return {"task": task.snapshot()}


def _regen_payload(request: Request, done: dict[str, Any]) -> dict[str, Any]:
    preview = done["preview"]
    text, append, section_id = done["text"], done["append"], done["section_id"]
    section = None if append else split_document(text).section(section_id)
    if section is None:
        new_inner = render_inner(preview.title, preview.new_body)
    else:  # keep the section's own heading line; only the body changes
        mini = section.open_line + section.inner + section.close_line
        new_inner = section_inner(replace_section(mini, section_id, preview.new_body), section_id)
    html = _fragment(
        request,
        "partials/regen_result.html",
        {
            "preview": preview,
            "append": append,
            **_diff_context(
                preview.old_body, preview.new_body, old_label="current", new_label="regenerated"
            ),
        },
    )
    return {
        "html": html,
        "new_inner": new_inner.replace("\r\n", "\n"),
        "title": preview.title,
        "backend": preview.backend,
        "model": preview.model,
    }


class ArchiveBody(NoteRef):
    section_id: str = Field(min_length=1, max_length=64)
    inner: str = Field(max_length=1_000_000)


@router.post("/ui/review/{mm3_id}/archive-section")
async def archive_previous(request: Request, mm3_id: str) -> dict[str, Any]:
    """Archive the editor's current version of a section before it is replaced (R12)."""
    from meetingmaster3.domain.note import Section

    body = await _body(request, ArchiveBody)
    root, path = _locate(request, mm3_id, body.path)
    title, old_body = parse_inner(body.inner)
    section = Section(id=body.section_id, title=title, body_markdown=old_body)
    parsed = parse_note(read_text(path))
    target = await asyncio.to_thread(
        archive_section,
        root,
        path,
        section,
        meeting_id=parsed.note.meta.id,
        newline=parsed.note.newline,
    )
    return {"archive": target.relative_to(root).as_posix()}


class AppendBody(NoteRef):
    base_sha: str = Field(min_length=64, max_length=64)
    section_id: str = Field(min_length=1, max_length=64)
    inner: str = Field(max_length=1_000_000)


@router.post("/ui/review/{mm3_id}/append-section")
async def append_fresh_section(request: Request, mm3_id: str) -> dict[str, Any]:
    """R11: write a regenerated copy of a damaged section as a new section at the end (before
    AI Recommendations). The damaged text stays where it is."""
    from meetingmaster3.domain.note import Section

    body = await _body(request, AppendBody)
    root, path = _locate(request, mm3_id, body.path)
    title, new_body = parse_inner(body.inner)
    current = read_text(path)
    new_text, sid = append_section(
        current, Section(id=body.section_id, title=title, body_markdown=new_body)
    )
    sha = await asyncio.to_thread(write_checked, root, path, new_text, expected_sha=body.base_sha)
    _store(request, mm3_id).put_base(new_text)
    return {"sha": sha, "section_id": sid}


# -- switch template ------------------------------------------------------------------------------


class SwitchBody(NoteRef):
    base_sha: str = Field(min_length=64, max_length=64)
    template: str = Field(min_length=1, max_length=64)
    backend: str | None = None
    model: str | None = None
    cloud_consent: bool = False


@router.post("/ui/review/{mm3_id}/switch/preview")
async def switch_preview(request: Request, mm3_id: str) -> dict[str, Any]:
    """Start writing the whole note again with another template. Returns at once with the task;
    the diff and the apply token come from ``task/{id}/result`` when it is done."""
    body = await _body(request, SwitchBody)
    _, path = _locate(request, mm3_id, body.path)
    store = _store(request, mm3_id)
    text = base_text(store, body.base_sha)
    settings = _settings(request)
    library = template_library(settings, request.app.state.paths.data_dir)
    lookup = backend_lookup(request)
    estimate = await _estimator(request)

    async def work(task: LongTask) -> dict[str, Any]:
        result = await switch_template(
            settings,
            library,
            lookup,
            path=path,
            text=text,
            template_id=body.template,
            backend=body.backend or None,
            model=body.model or None,
            cloud_consent=body.cloud_consent,
            progress=task.update,
            step=task.set_step,
            on_context=lambda duration, local: setattr(
                task, "expected_s", estimate(duration, local)
            ),
        )
        token = store.put_pending(body.base_sha, result.text, result.info())
        return {"result": result, "token": token, "text": text}

    task = _tasks(request).start(check_mm3_id(mm3_id), "switch", work)
    return {"task": task.snapshot()}


def _switch_payload(request: Request, done: dict[str, Any]) -> dict[str, Any]:
    result = done["result"]
    html = _fragment(
        request,
        "partials/switch_result.html",
        {
            "result": result,
            **_diff_context(
                done["text"], result.text, old_label="current note", new_label="new note"
            ),
        },
    )
    return {"html": html, "token": done["token"]}


# -- long-task progress (switch and regenerate) ----------------------------------------------------


def _tasks(request: Request) -> TaskRegistry:
    registry: TaskRegistry | None = getattr(request.app.state, "long_tasks", None)
    if registry is None:
        registry = request.app.state.long_tasks = TaskRegistry()
    return registry


async def _estimator(request: Request) -> Callable[[float | None, bool], float | None]:
    """``(duration, backend is local) -> expected seconds`` from the hardware profile's measured
    notes speed (``None`` for a cloud backend, an unknown duration or an unknown profile)."""
    info = await asyncio.to_thread(get_hardware)
    rec = recommend(info, _settings(request).hardware.profile)

    def estimate(duration: float | None, local: bool) -> float | None:
        if not local or not duration or duration <= 0:
            return None
        return expected_seconds(rec.llm.estimate(duration))

    return estimate


def _task_of(request: Request, mm3_id: str, task_id: str) -> LongTask:
    task = _tasks(request).get(task_id)
    if task is None or task.mm3_id != check_mm3_id(mm3_id):
        raise MM3Error(
            "E_TASK_NOT_FOUND",
            "That action is no longer running.",
            "It was cancelled, finished long ago, or the server was restarted. Start it again.",
            status_code=404,
        )
    return task


@router.get("/ui/review/{mm3_id}/task")
async def current_task(request: Request, mm3_id: str) -> dict[str, Any]:
    """The note's running or last finished long action, for a page that was reloaded."""
    task = _tasks(request).for_note(check_mm3_id(mm3_id))
    return {"task": task.snapshot() if task else None}


@router.get("/ui/review/{mm3_id}/task/{task_id}")
async def task_status(request: Request, mm3_id: str, task_id: str) -> dict[str, Any]:
    return {"task": _task_of(request, mm3_id, task_id).snapshot()}


@router.get("/ui/review/{mm3_id}/task/{task_id}/result")
async def task_result(request: Request, mm3_id: str, task_id: str) -> dict[str, Any]:
    task = _task_of(request, mm3_id, task_id)
    if task.state is TaskState.RUNNING:
        raise MM3Error(
            "E_TASK_RUNNING", "That action is still running.", "Wait for it to finish.", 409
        )
    if task.state is TaskState.CANCELLED:
        raise MM3Error("E_TASK_CANCELLED", "That action was cancelled.", "", status_code=409)
    if task.error is not None:
        raise task.error
    if task.kind == "switch":
        return _switch_payload(request, task.result)
    return _regen_payload(request, task.result)


@router.post("/ui/review/{mm3_id}/task/{task_id}/cancel")
async def task_cancel(request: Request, mm3_id: str, task_id: str) -> dict[str, Any]:
    """Stop a running action (the model call is interrupted), or dismiss a finished one."""
    task = _task_of(request, mm3_id, task_id)
    await _tasks(request).cancel(task)
    return {"task": task.snapshot()}


class SwitchApplyBody(NoteRef):
    token: str = Field(min_length=32, max_length=32)


@router.post("/ui/review/{mm3_id}/switch/apply")
async def switch_apply(request: Request, mm3_id: str) -> dict[str, Any]:
    body = await _body(request, SwitchApplyBody)
    root, path = _locate(request, mm3_id, body.path)
    store = _store(request, mm3_id)
    pending = store.pending(body.token)
    if pending is None:
        raise MM3Error(
            "E_SWITCH_EXPIRED",
            "That template preview is no longer available.",
            "Preview the template switch again.",
            status_code=409,
        )
    text, info = pending
    check_note(text, check_mm3_id(mm3_id))
    if text_sha(read_text(path)) != info["base_sha"]:
        raise MM3Error(
            "E_NOTE_CHANGED",
            "The note changed since the preview was made.",
            "Reload the page and preview the template switch again.",
            status_code=409,
        )
    archived = await asyncio.to_thread(archive_note, root, path)
    sha = await asyncio.to_thread(write_checked, root, path, text, expected_sha=info["base_sha"])
    store.clear_pending()
    store.clear_draft()
    store.put_base(text)
    running = _tasks(request).for_note(check_mm3_id(mm3_id))
    if running is not None and running.kind == "switch":
        _tasks(request).discard(running)  # its result has been applied
    return {"sha": sha, "archive": archived.relative_to(root).as_posix(), **info}


# -- rename speakers ------------------------------------------------------------------------------


class RenameBody(NoteRef):
    base_sha: str = Field(min_length=64, max_length=64)
    names: dict[str, str]
    companion_sha: str | None = None


def _rename_inputs(request: Request, mm3_id: str, body: RenameBody) -> tuple[Any, ...]:
    root, path = _locate(request, mm3_id, body.path)
    text = read_text(path)
    if text_sha(text) != body.base_sha:
        raise MM3Error(
            "E_NOTE_CHANGED",
            "The note changed since you opened it (or has unsaved edits in another tab).",
            "Save or reload first, then rename the speakers.",
            status_code=409,
        )
    found = find_companion(path, parse_note(text))
    if found is None:
        raise transcript_missing()
    companion_path, companion = found
    companion_text = read_text(companion_path)
    plan = plan_rename(text, companion, companion_text, body.names)
    return root, path, text, companion_path, companion, companion_text, plan


@router.post("/ui/review/{mm3_id}/speakers/preview")
async def rename_preview(request: Request, mm3_id: str) -> dict[str, Any]:
    body = await _body(request, RenameBody)
    root, _path, text, companion_path, _, companion_text, plan = _rename_inputs(
        request, mm3_id, body
    )
    html = _fragment(
        request,
        "partials/rename_result.html",
        {
            "plan": plan,
            "note_rows": [r for r in side_by_side(text, plan.note_text) if r.kind != "equal"],
            "companion_changes": sum(
                r.kind != "equal" for r in side_by_side(companion_text, plan.companion_text)
            ),
            "companion_rel": companion_path.relative_to(root).as_posix(),
        },
    )
    return {"html": html, "companion_sha": text_sha(companion_text)}


@router.post("/ui/review/{mm3_id}/speakers/apply")
async def rename_apply(request: Request, mm3_id: str) -> dict[str, Any]:
    body = await _body(request, RenameBody)
    root, path, _text, companion_path, companion, companion_text, plan = _rename_inputs(
        request, mm3_id, body
    )
    if body.companion_sha and text_sha(companion_text) != body.companion_sha:
        raise MM3Error(
            "E_NOTE_CHANGED",
            "The transcript changed since the preview was made.",
            "Preview the rename again.",
            status_code=409,
        )
    atomic_write_text(companion_path, plan.companion_text, overwrite=True, vault_root=root)
    sha = write_checked(root, path, plan.note_text, expected_sha=body.base_sha)
    refresh_readable(
        root, path, companion_path, enabled=_settings(request).generation.readable_transcript
    )
    store = _store(request, mm3_id)
    store.put_base(plan.note_text)
    store.clear_draft()
    runner = get_runner(request)
    job_id = find_job(runner, check_mm3_id(mm3_id), None)
    job_updated = False
    if job_id is not None:
        folder = job_dir(runner.jobs_root, job_id)
        if folder.is_dir():
            save_job_speakers(folder, plan.speaker_map, companion.doc.transcript)
            job_updated = True
    return {
        "sha": sha,
        "changes": [asdict(c) for c in plan.changes],
        "job_updated": job_updated,
    }


# -- title & date (Phase 15d) ---------------------------------------------------------------------


class RetitleBody(NoteRef):
    base_sha: str = Field(min_length=64, max_length=64)
    title: str = Field(max_length=1000)
    date: dt.date
    time: str = Field(default="", max_length=8)
    """``HH:MM``, or empty for "time unknown"."""
    digest: str | None = Field(default=None, min_length=64, max_length=64)


def _clock(value: str) -> dt.time | None:
    if not value.strip():
        return None
    try:
        return dt.time.fromisoformat(value.strip())
    except ValueError as exc:
        raise MM3Error(
            "E_RETITLE_INVALID", f"{value!r} is not a time.", "Use HH:MM, or leave it empty.", 422
        ) from exc


def _retitle_plan(request: Request, mm3_id: str, body: RetitleBody) -> Any:
    root, path = _locate(request, mm3_id, body.path)
    if text_sha(read_text(path)) != body.base_sha:
        raise MM3Error(
            "E_NOTE_CHANGED",
            "The note changed since you opened it (or has unsaved edits in another tab).",
            "Save or reload first, then change the title and date.",
            status_code=409,
        )
    return plan_retitle(
        root,
        path,
        title=body.title,
        date=body.date,
        time=_clock(body.time),
        output_subfolder=_settings(request).vault.output_subfolder,
    )


@router.post("/ui/review/{mm3_id}/retitle/preview")
async def retitle_preview(request: Request, mm3_id: str) -> dict[str, Any]:
    body = await _body(request, RetitleBody)
    plan = await asyncio.to_thread(_retitle_plan, request, mm3_id, body)
    html = _fragment(request, "partials/retitle_result.html", {"plan": plan.to_dict()})
    return {"html": html, "digest": plan.digest, "blocked": bool(plan.blocked), "empty": plan.empty}


@router.post("/ui/review/{mm3_id}/retitle/apply")
async def retitle_apply(request: Request, mm3_id: str) -> dict[str, Any]:
    body = await _body(request, RetitleBody)
    mm3_id = check_mm3_id(mm3_id)
    store = _store(request, mm3_id)
    if store.draft() is not None:
        raise MM3Error(
            "E_UNSAVED_EDITS",
            "This note has unsaved edits (a draft is kept for it).",
            "Save them to the vault or discard them, then change the title and date.",
            status_code=409,
        )
    running = _tasks(request).for_note(mm3_id)
    if running is not None and running.state is TaskState.RUNNING:
        raise MM3Error(
            "E_TASK_RUNNING",
            "A template switch or regeneration is running for this note.",
            "Wait for it to finish (or cancel it), then change the title and date.",
            status_code=409,
        )
    if not body.digest:
        raise MM3Error("E_RETITLE_INVALID", "Preview the changes first.", "", status_code=422)
    runner = get_runner(request)

    def run() -> Any:
        plan = _retitle_plan(request, mm3_id, body)
        return plan, apply_retitle(
            plan,
            data_dir=request.app.state.paths.data_dir,
            db=runner.db,
            jobs_root=runner.jobs_root,
            expected_digest=body.digest,
        )

    plan, result = await asyncio.to_thread(run)
    store.put_base(read_text(plan.root / result.note_rel))
    store.clear_pending()
    return {
        "url": f"/meetings/{mm3_id}?path={quote(result.note_rel, safe='')}",
        "note": result.note_rel,
        "backup": result.backup,
        "links": plan.link_count,
        "warnings": result.warnings,
    }


# -- note-only mode: locate the transcript, or process the audio again --------------------------


@router.get("/ui/review/{mm3_id}/locate", response_class=HTMLResponse)
async def locate_transcript(request: Request, mm3_id: str, path: str) -> HTMLResponse:
    root, note = _locate(request, mm3_id, path)
    found = await asyncio.to_thread(find_companions, root, check_mm3_id(mm3_id))
    items = [
        {
            "rel": f.relative_to(root).as_posix(),
            "same_folder": f.parent.resolve() == note.parent.resolve(),
        }
        for f in found
    ]
    return render(
        request,
        "partials/locate.html",
        {"items": items, "folder": note.parent.relative_to(root).as_posix() or "/"},
    )


class LinkBody(NoteRef):
    base_sha: str = Field(min_length=64, max_length=64)
    transcript: str = Field(min_length=1, max_length=4096)


@router.post("/ui/review/{mm3_id}/link-transcript")
async def link_transcript(request: Request, mm3_id: str) -> dict[str, Any]:
    """Point the note's ``mm3-transcript`` at a companion file found next to it."""
    body = await _body(request, LinkBody)
    root, path = _locate(request, mm3_id, body.path)
    target = confine(root, body.transcript)
    info = read_identity(target) if target.is_file() else None
    if (
        info is None
        or not info.is_transcript
        or info.mm3_id != check_mm3_id(mm3_id)
        or target.parent.resolve() != path.parent.resolve()
    ):
        raise MM3Error(
            E_TRANSCRIPT_MISSING,
            "That file is not this meeting's transcript, or it is not in the note's folder.",
            "Move the transcript next to the note, then link it.",
            status_code=422,
        )
    text = read_text(path)
    parsed = parse_note(text)
    ref = target.name.removesuffix(NOTE_SUFFIX)
    note = parsed.note.with_meta(parsed.note.meta.model_copy(update={"transcript_ref": ref}))
    new_text = render_note(note, base=parsed)
    readable = refresh_readable(
        root, path, target, enabled=_settings(request).generation.readable_transcript
    )
    if readable is not None:
        new_text = with_transcript_link(new_text, readable_link(readable))
    sha = write_checked(root, path, new_text, expected_sha=body.base_sha)
    _store(request, mm3_id).put_base(new_text)
    return {"sha": sha, "transcript": wikilink(ref)}


@router.post("/ui/review/{mm3_id}/reprocess")
async def reprocess(request: Request, mm3_id: str) -> dict[str, Any]:
    """Start a new job from the meeting's retained audio (it writes a new note)."""
    body = await _body(request, NoteRef)
    _, path = _locate(request, mm3_id, body.path)
    runner = get_runner(request)
    job_id = find_job(runner, check_mm3_id(mm3_id), None)
    if job_id is None:
        raise MM3Error("E_AUDIO_MISSING", "No recording is linked to this note.", "", 404)
    source = runner.audio_file(job_id)  # raises E_AUDIO_EXPIRED / E_AUDIO_MISSING
    old = runner.jobs.get(job_id)
    parsed = parse_note(read_text(path))
    new_id = new_job_id()
    folder = job_dir(runner.jobs_root, new_id)
    folder.mkdir(parents=True, mode=0o700)
    audio_name = "original" + source.suffix  # retention recognises original.* (R8)
    await asyncio.to_thread(shutil.copyfile, source, folder / audio_name)
    meta = parsed.note.meta
    # Cloud consent is per job (S6): the new job asks again.
    inherited = {
        k: v for k, v in old.settings.items() if k not in {"cloud_consent", "cloud_consent_for"}
    }
    options = JobOptions.model_validate(
        {
            **inherited,
            "title": meta.title,
            "meeting_date": meta.date.date() if meta.date else old.settings.get("meeting_date"),
            "template": meta.template_id or old.settings.get("template"),
        }
    )
    runner.create_job(
        new_id,
        options=options,
        source_filename=old.source_filename,
        audio_name=audio_name,
        duration_seconds=old.duration_seconds,
    )
    return {"job_id": new_id, "url": f"/jobs/{new_id}"}
