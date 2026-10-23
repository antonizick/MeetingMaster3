"""HTML pages and HTMX partials: the core flow of the web UI (Phase 10).

Pages are rendered on the server. The job page keeps itself current by re-fetching one partial
whenever the SSE stream reports progress (``static/app.js``), so a reload always shows the
real state. Every state-changing route is POST/DELETE and passes the CSRF middleware (S2); the
HTMX requests carry the token in ``hx-headers`` on ``<body>``.
"""

from __future__ import annotations

import asyncio
import datetime as dt
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from meetingmaster3 import __version__
from meetingmaster3.config.editing import save_settings
from meetingmaster3.domain.filenames import parse_filename
from meetingmaster3.errors import MM3Error
from meetingmaster3.feedback.context import feedback_context
from meetingmaster3.feedback.store import FeedbackStore
from meetingmaster3.hardware.detect import get_hardware
from meetingmaster3.hardware.recommend import format_eta, recommend
from meetingmaster3.jobs.files import check_job_id, job_dir
from meetingmaster3.jobs.models import FINAL, JobStatus
from meetingmaster3.llm.registry import BackendRegistry
from meetingmaster3.speakers.stages import SPEAKERS_FILE, normalise_answer
from meetingmaster3.speakers.store import VoiceprintStore
from meetingmaster3.storage.repositories import RecentMeetingsRepository
from meetingmaster3.templates import model_check
from meetingmaster3.templates.loader import MANIFEST_NAME, install_builtins
from meetingmaster3.templates.stages import WRITTEN_FILE, template_library
from meetingmaster3.vault import relink
from meetingmaster3.vault.io import read_text
from meetingmaster3.vault.paths import is_inside, resolve_vault_root
from meetingmaster3.vault.picker import browse, read_identity
from meetingmaster3.web import views
from meetingmaster3.web.api.jobs import get_runner
from meetingmaster3.web.api.speakers import _read as read_json_file
from meetingmaster3.web.paging import (
    JOBS_PER_PAGE,
    NOTES_PER_PAGE,
    page_params,
    pager,
    paginate,
    parse_page,
    picker_context,
    with_params,
)
from meetingmaster3.web.render import render_markdown

WEB_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=WEB_DIR / "templates")
templates.env.filters["duration"] = views.format_duration
templates.env.globals["STATUS_LABELS"] = views.STATUS_LABELS
templates.env.globals["STAGE_ICONS"] = views.STAGE_ICONS

router = APIRouter()

NAV = (
    ("new", "/", "New meeting"),
    ("recent", "/meetings", "Meetings"),
    ("search", "/search", "Search"),
    ("ask", "/ask", "Ask-AI"),
    ("templates", "/templates", "Templates"),
    ("settings", "/settings", "Settings"),
)


def render(
    request: Request, name: str, context: dict[str, Any] | None = None, status_code: int = 200
) -> HTMLResponse:
    base = {
        "version": __version__,
        "csrf_token": getattr(request.state, "csrf_token", ""),
        "nav": NAV,
        "active": "",
    }
    return templates.TemplateResponse(
        request, name, {**base, **(context or {})}, status_code=status_code
    )


def _settings(request: Request) -> Any:
    return request.app.state.settings


def _vault_configured(request: Request) -> bool:
    return _settings(request).vault.path is not None


def _hx_redirect(url: str) -> Response:
    return Response(status_code=200, headers={"HX-Redirect": url})


# -- health ----------------------------------------------------------------------------------------


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


# -- vault setup -----------------------------------------------------------------------------------


@router.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request) -> HTMLResponse:
    settings = _settings(request)
    path = str(settings.vault.path or "")
    subfolder = settings.vault.output_subfolder or views.DEFAULT_OUTPUT_SUBFOLDER
    check = await asyncio.to_thread(views.check_vault, path, subfolder)
    return render(
        request,
        "setup.html",
        {"active": "settings", "check": check, "configured": bool(path), "saved": False},
    )


@router.get("/setup/check", response_class=HTMLResponse)
async def setup_check(
    request: Request, vault_path: str = "", output_subfolder: str = ""
) -> HTMLResponse:
    check = await asyncio.to_thread(views.check_vault, vault_path, output_subfolder)
    return render(request, "partials/vault_check.html", {"check": check})


@router.post("/setup", response_class=HTMLResponse)
async def setup_save(
    request: Request,
    vault_path: str = Form(""),
    output_subfolder: str = Form(views.DEFAULT_OUTPUT_SUBFOLDER),
) -> Response:
    check = await asyncio.to_thread(views.check_vault, vault_path, output_subfolder)
    if not check.ok or check.root is None:
        return render(request, "partials/vault_check.html", {"check": check, "failed": True})
    settings = _settings(request)
    settings.vault.path = check.root
    settings.vault.output_subfolder = check.subfolder
    paths = request.app.state.paths
    settings.save(paths.config_file)
    try:
        install_builtins(
            check.root, settings.vault.templates_subfolder, paths.data_dir / MANIFEST_NAME
        )
    except (MM3Error, OSError) as exc:
        check.warnings.append(f"The starter templates were not installed: {exc}")
        return render(request, "partials/vault_check.html", {"check": check, "saved": True})
    return _hx_redirect("/")


# -- new meeting -----------------------------------------------------------------------------------


def _backend_choices(registry: BackendRegistry) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for name in registry.names():
        try:
            out.append(registry.describe(name))
        except MM3Error as exc:  # e.g. a backend whose optional dependency is missing
            out.append(
                {
                    "name": name,
                    "badge": "unavailable",
                    "requires_consent": False,
                    "error": exc.message,
                }
            )
    return out


@router.get("/", response_class=HTMLResponse)
async def new_meeting(request: Request) -> Response:
    if not _vault_configured(request):
        return RedirectResponse("/setup", status_code=303)
    settings = _settings(request)
    library = await asyncio.to_thread(template_library, settings, request.app.state.paths.data_dir)
    registry: BackendRegistry = request.app.state.llm_registry
    backends = _backend_choices(registry)
    default_backend = next(
        (b for b in backends if b["name"] == registry.default_name), backends[0] if backends else {}
    )
    return render(
        request,
        "new.html",
        {
            "active": "new",
            "templates_list": [e.to_dict() for e in library.listing()],
            "default_template": settings.generation.default_template,
            "backends": backends,
            "default_backend": default_backend,
            "max_upload_mb": settings.audio.max_upload_mb,
            "diarize_default": settings.transcription.diarize,
        },
    )


@router.get("/ui/parse-filename")
async def parse_name(name: str = "") -> dict[str, str | None]:
    guess = parse_filename(name[:500])
    return {
        "title": guess.title,
        "date": guess.date.isoformat() if guess.date else None,
        "time": guess.time.strftime("%H:%M") if guess.time else None,
    }


@router.get("/ui/hardware", response_class=HTMLResponse)
async def hardware_panel(
    request: Request, duration: float | None = None, diarize: bool = True
) -> HTMLResponse:
    """The hardware confirmation: detected hardware, recommended settings and the ETA."""
    settings = _settings(request)
    info = await asyncio.to_thread(get_hardware)
    rec = recommend(info, settings.hardware.profile, diarize=diarize)
    eta = notes_eta = None
    if duration and duration > 0:
        low, high = rec.transcription.estimate(duration)
        eta = format_eta(low, high)
        notes = rec.llm.estimate(duration)
        if notes is not None and _default_backend_is_local(request):
            notes_eta = format_eta(*notes)
    return render(
        request,
        "partials/hardware.html",
        {"info": info, "rec": rec, "eta": eta, "notes_eta": notes_eta, "duration": duration},
    )


def _default_backend_is_local(request: Request) -> bool:
    registry: BackendRegistry = request.app.state.llm_registry
    try:
        return bool(registry.get(None).is_local)
    except MM3Error:
        return False


# -- job page --------------------------------------------------------------------------------------


def review_link(written: dict[str, Any]) -> str:
    """The review workspace for a written job's note (the read-only preview as a fallback)."""
    if written.get("mm3_id") and written.get("note_relative"):
        return f"/meetings/{written['mm3_id']}?path={quote(written['note_relative'])}"
    return f"/preview?path={quote(written['note_path'], safe='')}"


def _job_context(request: Request, job_id: str) -> dict[str, Any]:
    runner = get_runner(request)
    job = runner.describe(check_job_id(job_id))
    now = dt.datetime.now(dt.UTC)
    for stage in job["stages"]:
        stage["elapsed"] = views.stage_elapsed(stage, now)
    written: dict[str, Any] | None = None
    if job["status"] == JobStatus.WRITTEN.value:
        written = read_json_file(job_dir(runner.jobs_root, job_id) / WRITTEN_FILE)
        if written and written.get("note_path"):
            written["obsidian_link"] = views.obsidian_link(written["note_path"])
            written["preview_link"] = review_link(written)
            written["feedback"] = feedback_context(
                FeedbackStore(runner.db),
                str(written.get("mm3_id") or ""),
                template_id=written.get("template"),
                backend=job["options"].get("backend") or _settings(request).llm.default_backend,
                model=job["options"].get("model"),
            )
    current = next((s for s in job["stages"] if s["status"] in {"running", "waiting"}), None)
    return {
        "job": job,
        "title": views.job_title(job),
        "failure": views.failure_of(job),
        "written": written,
        "current": current,
        "final": JobStatus(job["status"]) in FINAL,
        "cancellable": job["status"] in views.CANCELLABLE,
        "leave_note": views.leave_note(job),
        "tab_title": views.tab_title(job, current),
    }


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_page(request: Request, job_id: str) -> HTMLResponse:
    return render(request, "job.html", {"active": "recent", **_job_context(request, job_id)})


@router.get("/ui/jobs/{job_id}/panel", response_class=HTMLResponse)
async def job_panel(request: Request, job_id: str) -> HTMLResponse:
    return render(request, "partials/job_panel.html", _job_context(request, job_id))


def _panel(request: Request, job_id: str) -> HTMLResponse:
    return render(request, "partials/job_panel.html", _job_context(request, job_id))


@router.post("/ui/jobs/{job_id}/cancel", response_class=HTMLResponse)
async def job_cancel(request: Request, job_id: str) -> HTMLResponse:
    await get_runner(request).cancel(check_job_id(job_id))
    return _panel(request, job_id)


@router.post("/ui/jobs/{job_id}/retry", response_class=HTMLResponse)
async def job_retry(request: Request, job_id: str) -> HTMLResponse:
    """Resume a failed, cancelled or interrupted job, optionally with ``o_<option>`` overrides."""
    runner = get_runner(request)
    form = await request.form()
    overrides: dict[str, Any] = {}
    for name, cast in views.RETRY_OVERRIDES.items():
        raw = form.get(f"o_{name}")
        if isinstance(raw, str) and raw.strip():
            try:
                overrides[name] = cast(raw.strip())
            except ValueError as exc:
                raise MM3Error("E_BODY_INVALID", f"{name} must be a number.", "") from exc
    runner.resume(check_job_id(job_id), overrides)
    return _panel(request, job_id)


async def _model_choices(request: Request) -> list[dict[str, Any]]:
    """Every backend with the models a failed job could be retried with. Local backends list
    their installed models (unusable ones are shown disabled, with the reason); cloud backends
    offer their default model, and are asked for consent again before anything is sent."""
    registry: BackendRegistry = request.app.state.llm_registry
    cap = _settings(request).generation.max_context
    groups: list[dict[str, Any]] = []
    for name in registry.names():
        backend = registry.get(name)
        cfg = registry.config(name)
        group: dict[str, Any] = {
            "name": name,
            "local": backend.is_local,
            "models": [],
            "suggested": None,
            "error": "",
        }
        if backend.is_local:
            try:
                found = await backend.list_models()
            except MM3Error as exc:
                group["error"] = exc.message
                found = []
            group["suggested"] = model_check.suggest(found, backend, cap)
            for m in found:
                ok = model_check.usable(m, backend, cap)
                why = (
                    ""
                    if ok
                    else ("embedding model" if m.can_generate is False else "context too small")
                )
                group["models"].append({"id": m.id, "window": m.context_window, "why": why})
        elif cfg.default_model:
            group["models"].append({"id": cfg.default_model, "window": None, "why": ""})
        if group["models"] or group["error"]:
            groups.append(group)
    return groups


@router.get("/ui/jobs/{job_id}/model-choice", response_class=HTMLResponse)
async def job_model_choice(request: Request, job_id: str) -> HTMLResponse:
    """The "try another model" form shown when writing the notes failed."""
    job = get_runner(request).describe(check_job_id(job_id))
    registry: BackendRegistry = request.app.state.llm_registry
    groups = await _model_choices(request)
    failed = (job["options"].get("backend") or registry.default_name, job["options"].get("model"))
    selected = next(
        (
            (g["name"], g["suggested"])
            for g in groups
            if g["suggested"] and (g["name"], g["suggested"]) != failed
        ),
        None,
    )
    return render(
        request,
        "partials/model_choice.html",
        {
            "job": job,
            "groups": groups,
            "selected": selected,
            "failed": failed,
            "usable_count": sum(not m["why"] for g in groups for m in g["models"]),
        },
    )


@router.post("/ui/jobs/{job_id}/retry-model", response_class=HTMLResponse)
async def job_retry_model(
    request: Request,
    job_id: str,
    choice: str = Form(...),
    make_default: str = Form(""),
) -> HTMLResponse:
    """Retry a failed job with another backend/model (``choice`` is ``backend:model``); the
    finished transcript and speaker names are kept, so only the notes are written again."""
    check_job_id(job_id)
    registry: BackendRegistry = request.app.state.llm_registry
    settings = _settings(request)
    name, _, model = choice.partition(":")
    model = model.strip()
    if name not in registry.names() or not model:
        raise MM3Error("E_BODY_INVALID", "Choose one of the listed models.", "", status_code=422)
    await model_check.preflight(registry, settings, name, model)
    if make_default:
        backends = dict(settings.llm.backends)
        cfg = registry.config(name)
        backends[name] = cfg.model_copy(update={"default_model": model})
        settings.llm.backends = backends
        save_settings(settings, request.app.state.paths.config_file)
        registry.invalidate()
    get_runner(request).resume(job_id, {"backend": name, "model": model})
    return _panel(request, job_id)


@router.post("/ui/jobs/{job_id}/language", response_class=HTMLResponse)
async def job_language(
    request: Request, job_id: str, action: str = Form(...), language: str = Form("")
) -> HTMLResponse:
    answer: dict[str, Any] = {"action": action}
    if language.strip():
        answer["language"] = language.strip()
    get_runner(request).submit_input(check_job_id(job_id), answer)
    return _panel(request, job_id)


@router.post("/ui/jobs/{job_id}/consent", response_class=HTMLResponse)
async def job_consent(request: Request, job_id: str, choice: str = Form(...)) -> HTMLResponse:
    """Answer the cloud-consent question: ``allow``, ``deny`` or ``local`` (use a local model)."""
    runner = get_runner(request)
    check_job_id(job_id)
    if choice == "local":
        registry: BackendRegistry = request.app.state.llm_registry
        local = next((n for n in registry.names() if registry.get(n).is_local), None)
        if local is None:
            raise MM3Error(
                "E_LLM_CONFIG",
                "No local LLM backend is configured.",
                "Configure Ollama, or allow the cloud backend for this meeting.",
                status_code=409,
            )
        runner.update_options(job_id, {"backend": local, "model": None})
        runner.submit_input(job_id, {"consent": True})
    elif choice in {"allow", "deny"}:
        runner.submit_input(job_id, {"consent": choice == "allow"})
    else:
        raise MM3Error("E_BODY_INVALID", "Unknown consent choice.", "", status_code=422)
    return _panel(request, job_id)


# -- speakers --------------------------------------------------------------------------------------


@router.get("/jobs/{job_id}/speakers", response_class=HTMLResponse)
async def speakers_page(request: Request, job_id: str) -> Response:
    from meetingmaster3.web.api.speakers import get_speakers

    runner = get_runner(request)
    data = await get_speakers(request, job_id)
    job = runner.jobs.get(check_job_id(job_id))
    people: list[dict[str, Any]] = []
    if data["voiceprints_enabled"]:
        store = VoiceprintStore(runner.db, enabled=True)
        people = [p.to_dict() for p in store.list_people()]
    library = await asyncio.to_thread(
        template_library, _settings(request), request.app.state.paths.data_dir
    )
    confirmed = (data.get("confirmed") or {}).get("speakers", {})
    return render(
        request,
        "speakers.html",
        {
            "active": "recent",
            "data": data,
            "job": job.to_dict(),
            "title": views.job_title(job.to_dict()),
            "people": people,
            "confirmed": confirmed,
            "templates_list": [e.to_dict() for e in library.listing() if e.valid],
            "template_id": job.settings.get("template")
            or _settings(request).generation.default_template,
            "voiceprints_enabled": data["voiceprints_enabled"]
            and _settings(request).privacy.voiceprints_enabled,
        },
    )


@router.post("/ui/jobs/{job_id}/speakers")
async def speakers_submit(request: Request, job_id: str) -> Response:
    """Form post of the Name Speakers screen: ``name__<label>``, ``person__<label>``,
    ``enroll__<label>``, ``same__<label>`` (merge with another label) and ``template``."""
    runner = get_runner(request)
    job = runner.jobs.get(check_job_id(job_id))
    form = await request.form()
    payload = read_json_file(job_dir(runner.jobs_root, job.id) / SPEAKERS_FILE) or {}
    labels = [s["label"] for s in payload.get("speakers", [])]

    def field(prefix: str, label: str) -> str:
        value = form.get(f"{prefix}__{label}")
        return value.strip() if isinstance(value, str) else ""

    entries: dict[str, dict[str, Any]] = {}
    for label in labels:
        name = field("name", label)
        if not name:
            continue  # left blank: the placeholder stays
        entry: dict[str, Any] = {"name": name, "enroll": bool(field("enroll", label))}
        person = field("person", label)
        if person:
            entry["person_id"] = person
        entries[label] = entry
    for label in labels:  # "same person as ...": copy the other speaker's answer
        other = field("same", label)
        if other and other != label and other in entries:
            entries[label] = dict(entries[other])
    answer = normalise_answer({"speakers": entries})
    for label, entry in answer["speakers"].items():
        if entry["person_id"]:
            store = VoiceprintStore(runner.db, enabled=runner.settings.privacy.voiceprints_enabled)
            if store.find(entry["person_id"]) is None:
                raise MM3Error(
                    "E_PERSON_NOT_FOUND",
                    f"Speaker {label}: the selected person is no longer stored.",
                    "Pick another suggestion or type a name.",
                    status_code=422,
                )
    template = form.get("template")
    if isinstance(template, str) and template and template != job.settings.get("template"):
        runner.update_options(job.id, {"template": template})
    runner.submit_input(job.id, answer)
    return _hx_redirect(f"/jobs/{job.id}")


# -- recent meetings -------------------------------------------------------------------------------


def _jobs_section(request: Request) -> dict[str, Any]:
    runner = get_runner(request)
    params = page_params(request.query_params)
    page = paginate(runner.jobs.count_jobs(), parse_page(params.get("jobs_page")), JOBS_PER_PAGE)
    jobs = [j.to_dict() for j in runner.jobs.list_jobs(None, limit=page.size, offset=page.offset)]
    for job in jobs:
        job["resumable"] = views.is_resumable(job["status"])
        job["label"] = views.job_title(job)
    own = {k: v for k, v in params.items() if k != "jobs_page"}
    return {
        "jobs": jobs,
        "jobs_qs": with_params("", {**own, "jobs_page": str(page.number)}),
        "jobs_pager": pager(
            page,
            param="jobs_page",
            params=own,
            href_base="/meetings",
            hx_base="/ui/meetings/jobs",
            label="Jobs",
        ),
    }


def _notes_section(
    request: Request,
    matches: dict[str, relink.Match] | None = None,
    message: str | None = None,
) -> dict[str, Any]:
    runner = get_runner(request)
    vault = _settings(request).vault.path
    repo = RecentMeetingsRepository(runner.db)
    params = page_params(request.query_params)
    page = paginate(repo.count(), parse_page(params.get("notes_page")), NOTES_PER_PAGE)
    notes: list[dict[str, Any]] = []
    for meeting in repo.recent(page.size, page.offset):
        item = meeting.to_dict()
        rel = views.vault_relative(vault, meeting.note_path)
        item["orphan"] = _orphan_reason(meeting.note_path, rel)
        match = (matches or {}).get(meeting.note_path)
        item["relink"] = _relink_view(match, vault) if match else None
        item["obsidian_link"] = views.obsidian_link(meeting.note_path)
        item["preview_link"] = (
            f"/open/note?path={quote(rel, safe='')}"
            if rel
            else f"/preview?path={quote(meeting.note_path, safe='')}"
        )
        notes.append(item)
    # The banner counts every entry, not just the ones on this page.
    orphans = sum(
        1
        for m in repo.recent(10_000)
        if _orphan_reason(m.note_path, views.vault_relative(vault, m.note_path))
    )
    own = {k: v for k, v in params.items() if k != "notes_page"}
    return {
        "notes": notes,
        "orphans": orphans,
        "scanned": matches is not None,
        "relink_clear": sum(1 for m in (matches or {}).values() if m.status == "found"),
        "relink_message": message,
        "notes_qs": with_params("", {**own, "notes_page": str(page.number)}),
        "notes_pager": pager(
            page,
            param="notes_page",
            params=own,
            href_base="/meetings",
            hx_base="/ui/meetings/notes",
            label="Notes in your vault",
        ),
    }


def _relink_view(match: relink.Match, vault: Path | str) -> dict[str, Any]:
    root = resolve_vault_root(vault)
    return {
        "status": match.status,
        "candidates": [c.rel(root) for c in match.candidates],
    }


@router.get("/meetings", response_class=HTMLResponse)
async def recent_page(request: Request) -> HTMLResponse:
    """Meetings: jobs, "Update older notes", notes in the vault and the vault browser. Each
    section pages on its own (``jobs_page``, ``notes_page``, ``browse_page``)."""
    params = page_params(request.query_params)
    root = resolve_vault_root(_settings(request).vault.path)
    listing = await asyncio.to_thread(browse, root, params.get("dir", ""))
    return render(
        request,
        "meetings.html",
        {
            "active": "recent",
            "rename_recoveries": getattr(request.app.state, "rename_recoveries", []),
            **_jobs_section(request),
            **_notes_section(request),
            **picker_context(listing, params),
        },
    )


@router.get("/ui/meetings/jobs", response_class=HTMLResponse)
async def meetings_jobs_partial(request: Request) -> HTMLResponse:
    return render(request, "partials/meetings_jobs.html", _jobs_section(request))


@router.get("/ui/meetings/notes", response_class=HTMLResponse)
async def meetings_notes_partial(request: Request) -> HTMLResponse:
    return render(request, "partials/meetings_notes.html", _notes_section(request))


def _orphan_reason(note_path: str, vault_relative: str | None) -> str | None:
    """Why a Meetings entry no longer leads anywhere (``None`` if it still does)."""
    if not Path(note_path).is_file():
        return "File not found"
    if vault_relative is None:
        return "Not in your vault"
    return None


@router.post("/ui/jobs/{job_id}/resume", response_class=HTMLResponse)
async def recent_resume(request: Request, job_id: str) -> Response:
    get_runner(request).resume(check_job_id(job_id))
    return _hx_redirect(f"/jobs/{job_id}")


@router.delete("/ui/jobs/{job_id}", response_class=HTMLResponse)
async def recent_delete(request: Request, job_id: str) -> HTMLResponse:
    get_runner(request).delete(check_job_id(job_id))
    # The section is re-rendered, so the page fills up again and, if that was the last row of
    # the last page, falls back to the previous page instead of showing nothing.
    return render(request, "partials/meetings_jobs.html", _jobs_section(request))


@router.post("/ui/recent/remove", response_class=HTMLResponse)
async def recent_note_remove(request: Request, path: str = Form(...)) -> HTMLResponse:
    """Forget one "Notes in your vault" entry. Only the list entry goes; the note file (if it
    still exists) is never touched, and the entry comes back if the note is opened again."""
    RecentMeetingsRepository(get_runner(request).db).remove(path)
    return render(request, "partials/meetings_notes.html", _notes_section(request))


@router.post("/ui/recent/prune", response_class=HTMLResponse)
async def recent_note_prune(request: Request) -> Response:
    """Forget every entry whose note is gone or is no longer inside the configured vault."""
    repo = RecentMeetingsRepository(get_runner(request).db)
    vault = _settings(request).vault.path
    for meeting in repo.recent(10_000):
        rel = views.vault_relative(vault, meeting.note_path)
        if _orphan_reason(meeting.note_path, rel):
            repo.remove(meeting.note_path)
    return render(request, "partials/meetings_notes.html", _notes_section(request))


async def _scan_orphans(request: Request) -> dict[str, relink.Match]:
    """Look for every orphaned entry's note in the current vault (reads note headers only)."""
    repo = RecentMeetingsRepository(get_runner(request).db)
    root = resolve_vault_root(_settings(request).vault.path)
    entries = repo.recent(10_000)
    matches = await asyncio.to_thread(relink.plan_relink, root, entries)
    return {m.entry.note_path: m for m in matches}


def _relink_summary(linked: int, matches: dict[str, relink.Match]) -> str:
    left = [m for m in matches.values() if m.status != "found"]
    none = sum(1 for m in left if m.status == "none")
    parts = [f"Re-linked {linked} {'entry' if linked == 1 else 'entries'}."] if linked else []
    if none:
        parts.append(f"{none} could not be found in your vault.")
    if len(left) - none:
        parts.append(f"{len(left) - none} match more than one note: choose which one below.")
    return " ".join(parts) or "Nothing to re-link."


@router.post("/ui/recent/relink/scan", response_class=HTMLResponse)
async def recent_relink_scan(request: Request) -> HTMLResponse:
    """Search the vault for the notes of orphaned entries (by ``mm3-id``); change nothing."""
    matches = await _scan_orphans(request)
    found = sum(1 for m in matches.values() if m.status == "found")
    message = (
        f"{found} of {len(matches)} can be re-linked automatically." if matches else "All good."
    )
    return render(
        request, "partials/meetings_notes.html", _notes_section(request, matches, message)
    )


@router.post("/ui/recent/relink/all", response_class=HTMLResponse)
async def recent_relink_all(request: Request) -> HTMLResponse:
    """Re-link every orphaned entry that has exactly one matching note in the vault."""
    repo = RecentMeetingsRepository(get_runner(request).db)
    matches = await _scan_orphans(request)
    linked = relink.apply_clear_matches(repo, matches.values())
    remaining = await _scan_orphans(request) if linked != len(matches) else {}
    return render(
        request,
        "partials/meetings_notes.html",
        _notes_section(request, remaining, _relink_summary(linked, remaining)),
    )


@router.post("/ui/recent/relink", response_class=HTMLResponse)
async def recent_relink_one(
    request: Request, path: str = Form(...), to: str = Form(...)
) -> HTMLResponse:
    """Re-link one entry to ``to`` (vault-relative). The target must be one of the notes the
    vault search found for that entry, so a forged request cannot point an entry anywhere else."""
    repo = RecentMeetingsRepository(get_runner(request).db)
    matches = await _scan_orphans(request)
    root = resolve_vault_root(_settings(request).vault.path)
    match = matches.get(path)
    chosen = next((c for c in match.candidates if c.rel(root) == to), None) if match else None
    if match is None or chosen is None:
        raise MM3Error(
            "E_NOTE_NOT_FOUND",
            "That note can no longer be matched to this entry.",
            "Search the vault again and pick one of the notes it finds.",
            status_code=404,
        )
    relink.apply_relink(repo, match.entry, chosen)
    remaining = await _scan_orphans(request)
    return render(
        request,
        "partials/meetings_notes.html",
        _notes_section(request, remaining, _relink_summary(1, remaining)),
    )


# -- preview ------------------------------------------------------------------


@router.get("/preview", response_class=HTMLResponse)
async def preview_note(request: Request, path: str) -> HTMLResponse:
    """A read-only, sanitised rendering of a vault note that is not an MM3 note (MM3 notes open
    in the review workspace, ``/meetings/{mm3_id}``)."""
    root = resolve_vault_root(_settings(request).vault.path)
    note = Path(path)
    if (
        not note.is_absolute()
        or note.suffix != ".md"
        or not note.is_file()
        or not is_inside(root, note)
    ):
        raise MM3Error(
            "E_NOTE_NOT_FOUND",
            "That note is not in the vault.",
            "Open it from the Meetings page, or from the meeting you just processed.",
            status_code=404,
        )
    text = await asyncio.to_thread(read_text, note.resolve())
    info = read_identity(note.resolve())
    review = None
    if info is not None and not info.is_transcript and not info.archived:
        rel = note.resolve().relative_to(root).as_posix()
        review = f"/open/note?path={quote(rel, safe='')}"
    return render(
        request,
        "preview.html",
        {
            "active": "recent",
            "review_link": review,
            "name": note.stem,
            "rendered": render_markdown(text),
            "obsidian_link": views.obsidian_link(str(note)),
        },
    )
