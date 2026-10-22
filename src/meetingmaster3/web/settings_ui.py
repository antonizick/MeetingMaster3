"""The Settings screen (``/settings/<tab>``): forms that round-trip to ``config.yaml``.

Each tab is a server-rendered form posted with HTMX (``hx-post``); the response is the tab
again, with inline errors or a "Saved" note. Settings are validated as a whole before any of them
is applied (``config.editing``), written atomically with mode 0600, and take effect at once
unless the field says a restart is needed. Secrets are write-only: no page contains one.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import SecretStr

from meetingmaster3 import __version__
from meetingmaster3.config import editing
from meetingmaster3.config.editing import get_path
from meetingmaster3.config.settings import MODEL_NAME_PATTERN, BackendConfig, Settings
from meetingmaster3.errors import MM3Error
from meetingmaster3.hardware.detect import get_hardware
from meetingmaster3.hardware.doctor import run_checks
from meetingmaster3.hardware.recommend import recommend
from meetingmaster3.llm import recommendations
from meetingmaster3.llm.registry import BackendRegistry, kinds
from meetingmaster3.speakers.store import VoiceprintStore
from meetingmaster3.templates.stages import template_library
from meetingmaster3.transcription import hf_check, models
from meetingmaster3.vault.paths import confine
from meetingmaster3.web import settings_fields as sf
from meetingmaster3.web import views
from meetingmaster3.web.api.jobs import get_runner
from meetingmaster3.web.api.speakers import _store, _wipe_tokens
from meetingmaster3.web.llm import picker_for
from meetingmaster3.web.model_downloads import DownloadManager, build_plan
from meetingmaster3.web.pages import render

router = APIRouter()

AUTO = "auto"
"""Shown for ``search.embedding_backend: null`` (the local Ollama)."""
BACKEND_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
DEFAULT_WHISPER_CHOICES = ("large-v3-turbo", "medium", "small")


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def _registry(request: Request) -> BackendRegistry:
    registry: BackendRegistry = request.app.state.llm_registry
    return registry


async def _form(request: Request) -> dict[str, str]:
    data = await request.form()
    return {k: v for k, v in data.items() if isinstance(v, str)}


def _persist(request: Request) -> None:
    editing.save_settings(_settings(request), request.app.state.paths.config_file)
    _registry(request).invalidate()


def _tab_or_404(tab: str) -> str:
    if tab not in sf.TABS:
        raise MM3Error("E_NOT_FOUND", "There is no such settings tab.", "", status_code=404)
    return tab


def _can_open_folders() -> bool:
    docker = Path("/.dockerenv").exists() or bool(os.environ.get("MM3_IN_DOCKER"))
    return not docker and shutil.which("xdg-open") is not None


# -- shared rendering --------------------------------------------------------------------------


class State:
    """What the last submit of a tab left behind (for inline errors and notices)."""

    def __init__(
        self,
        submitted: Mapping[str, str] | None = None,
        errors: Mapping[str, str] | None = None,
        saved: bool = False,
        notices: list[str] | None = None,
    ) -> None:
        self.submitted = submitted
        self.errors = dict(errors or {})
        self.saved = saved
        self.notices = notices or []


def _views(
    settings: Settings,
    fields: tuple[sf.Field, ...],
    state: State,
    choices: Mapping[str, tuple[str, ...]] | None = None,
) -> list[sf.FieldView]:
    return [
        sf.view_of(settings, f, state.submitted, state.errors, (choices or {}).get(f.path))
        for f in fields
    ]


async def _tab_context(request: Request, tab: str, state: State) -> dict[str, Any]:
    settings = _settings(request)
    ctx: dict[str, Any] = {
        "tab": tab,
        "tabs": {k: v[0] for k, v in sf.TABS.items()},
        "state": state,
    }
    fields = sf.TABS[tab][1]
    choices: dict[str, tuple[str, ...]] = {}
    if tab == "notes":
        library = await asyncio.to_thread(
            template_library, settings, request.app.state.paths.data_dir
        )
        ids = tuple(e.id for e in library.listing() if e.valid and e.id)
        current = settings.generation.default_template
        choices["generation.default_template"] = ids if current in ids else (current, *ids)
    if tab == "search":
        names = _registry(request).names()
        current_backend = settings.search.embedding_backend
        extra = (current_backend,) if current_backend and current_backend not in names else ()
        choices["search.embedding_backend"] = (AUTO, *names, *extra)
    views_list = _views(settings, fields, state, choices)
    for v in views_list:
        if v.spec.path == "search.embedding_backend" and v.value == "":
            v.value = AUTO
    ctx["views"] = [v for v in views_list if not v.spec.advanced]
    ctx["advanced_views"] = [v for v in views_list if v.spec.advanced]
    if tab == "transcription":
        ctx.update(await _models_context(request))
    elif tab == "llm":
        ctx.update(await _llm_context(request))
    elif tab == "privacy":
        ctx.update(_privacy_context(request))
    elif tab == "search":
        ctx.update(_search_context(request))
    elif tab == "about":
        ctx.update(await _about_context(request))
    return ctx


def _tab_response(request: Request, tab: str, ctx: dict[str, Any], *, full: bool) -> HTMLResponse:
    ctx = {**ctx, "tab_template": f"settings/{tab}.html"}
    if full:
        return render(request, "settings/page.html", {"active": "settings", **ctx})
    return render(request, f"settings/{tab}.html", ctx)


async def _show(
    request: Request, tab: str, state: State | None = None, *, full: bool = False
) -> HTMLResponse:
    ctx = await _tab_context(request, tab, state or State())
    return _tab_response(request, tab, ctx, full=full)


# -- pages -------------------------------------------------------------------------------------


@router.get("/settings", response_class=HTMLResponse)
async def settings_home() -> Response:
    return RedirectResponse("/settings/vault", status_code=303)


@router.get("/settings/{tab}", response_class=HTMLResponse)
async def settings_tab(request: Request, tab: str) -> HTMLResponse:
    return await _show(request, _tab_or_404(tab), full=True)


async def _save_fields(
    request: Request, tab: str, extra_errors: dict[str, str], patch_override: dict[str, Any]
) -> tuple[State, bool]:
    form = await _form(request)
    fields = sf.TABS[tab][1]
    patch, errors = sf.parse_form(fields, form)
    patch.update(patch_override)
    errors = {**errors, **extra_errors}
    settings = _settings(request)
    if not errors:
        errors = editing.apply_patch(settings, patch)
    if errors:
        return State(submitted=form, errors=errors), False
    _persist(request)
    return State(saved=True), True


@router.post("/settings/vault", response_class=HTMLResponse)
async def save_vault(request: Request) -> HTMLResponse:
    form = await _form(request)
    errors: dict[str, str] = {}
    override: dict[str, Any] = {}
    check = await asyncio.to_thread(
        views.check_vault, form.get("vault.path", ""), form.get("vault.output_subfolder", "")
    )
    if not check.path:
        errors["vault.path"] = "Enter the folder of your Obsidian vault."
    elif check.root is None or check.errors:
        field_name = "vault.output_subfolder" if check.root is not None else "vault.path"
        errors[field_name] = " ".join(f"{e.message} {e.hint}".strip() for e in check.errors)
    else:
        override["vault.path"] = check.root
        for key in ("vault.templates_subfolder", "vault.attachments_subfolder"):
            try:
                confine(check.root, form.get(key, "").strip() or "x")
            except MM3Error as exc:
                errors[key] = f"{exc.message} {exc.hint}".strip()
    state, ok = await _save_fields(request, "vault", errors, override)
    if ok and check.warnings:
        state.notices.extend(check.warnings)
    return await _show(request, "vault", state)


@router.post("/settings/transcription", response_class=HTMLResponse)
async def save_transcription(request: Request) -> HTMLResponse:
    state, _ = await _save_fields(request, "transcription", {}, {})
    return await _show(request, "transcription", state)


@router.post("/settings/notes", response_class=HTMLResponse)
async def save_notes(request: Request) -> HTMLResponse:
    state, ok = await _save_fields(request, "notes", {}, {})
    if ok:
        state.notices.append(
            "Changing “Meetings processed at once” or the check interval needs a restart."
        )
    return await _show(request, "notes", state)


def _secret_set(value: object) -> bool:
    return isinstance(value, SecretStr) and bool(value.get_secret_value())


@router.post("/settings/llm/aws-keys", response_class=HTMLResponse)
async def save_aws_keys(request: Request) -> HTMLResponse:
    """The AWS access key pair for Bedrock backends (15g). Both keys or neither: half a pair
    would silently fall back to the AWS profile chain, so removing one removes both."""
    form = await _form(request)
    settings = _settings(request)
    paths = [f.path for f in sf.AWS_FIELDS]
    errors: dict[str, str] = {}
    override: dict[str, Any] = {}
    if any(form.get(f"clear:{p}") for p in paths):
        override = dict.fromkeys(paths)
    else:
        saved = {p: _secret_set(get_path(settings, p)) for p in paths}
        have = {p: bool((form.get(p) or "").strip()) or saved[p] for p in paths}
        if any(have.values()) and not all(have.values()):
            missing = next(p for p, ok in have.items() if not ok)
            errors[missing] = "Enter both keys: the access key ID and its secret access key."
    state, _ = await _save_fields(request, "llm", errors, override)
    return await _show(request, "llm", state)


@router.post("/settings/privacy", response_class=HTMLResponse)
async def save_privacy(request: Request) -> HTMLResponse:
    state, _ = await _save_fields(request, "privacy", {}, {})
    return await _show(request, "privacy", state)


@router.post("/settings/search", response_class=HTMLResponse)
async def save_search(request: Request) -> HTMLResponse:
    override: dict[str, Any] = {}
    form = await _form(request)
    if form.get("search.embedding_backend", "").strip() in ("", AUTO):
        override["search.embedding_backend"] = None
    state, ok = await _save_fields(request, "search", {}, override)
    if ok:
        service = _search_or_none(request)
        if service is not None and _settings(request).search.enabled:
            service.schedule()
            state.notices.append("The index is being brought up to date in the background.")
    return await _show(request, "search", state)


# -- search & ask: the meeting index (Phase 15i) -------------------------------------------------


def _search_or_none(request: Request) -> Any:
    return getattr(request.app.state, "search", None)


def _search(request: Request) -> Any:
    service = _search_or_none(request)
    if service is None:
        raise MM3Error(
            "E_SEARCH_UNAVAILABLE", "The search index is not running.", "Restart the app.", 503
        )
    return service


def _search_context(request: Request) -> dict[str, Any]:
    service = _search_or_none(request)
    return {"search_status": service.status() if service is not None else None}


def _search_status(request: Request, message: str = "") -> HTMLResponse:
    ctx = {**_search_context(request), "search_message": message}
    return render(request, "settings/_search_status.html", ctx)


@router.get("/settings/search/status", response_class=HTMLResponse)
async def search_status(request: Request) -> HTMLResponse:
    return _search_status(request)


async def _start_index(request: Request, *, rebuild: bool) -> HTMLResponse:
    service = _search(request)
    if not _settings(request).search.enabled:
        service.enable()
        _persist(request)
    service.start_update(rebuild=rebuild)
    return _search_status(request, "Rebuilding the index." if rebuild else "Updating the index.")


@router.post("/settings/search/update", response_class=HTMLResponse)
async def search_update(request: Request) -> HTMLResponse:
    return await _start_index(request, rebuild=False)


@router.post("/settings/search/rebuild", response_class=HTMLResponse)
async def search_rebuild(request: Request) -> HTMLResponse:
    return await _start_index(request, rebuild=True)


@router.post("/settings/search/cancel", response_class=HTMLResponse)
async def search_cancel(request: Request) -> HTMLResponse:
    await _search(request).cancel()
    return _search_status(request, "Stopped. What was indexed so far is kept.")


@router.post("/settings/search/delete", response_class=HTMLResponse)
async def search_delete(request: Request) -> HTMLResponse:
    removed = await _search(request).delete_index()
    _persist(request)  # delete_index switched search.enabled off
    word = "file" if len(removed) == 1 else "files"
    return _search_status(
        request, f"The index was deleted ({len(removed)} {word}) and indexing is off."
    )


# -- transcription: token test and model downloads ---------------------------------------------


def _download_manager(request: Request) -> DownloadManager:
    manager: DownloadManager | None = getattr(request.app.state, "model_downloads", None)
    if manager is None:
        manager = request.app.state.model_downloads = DownloadManager()
    return manager


async def _models_context(request: Request) -> dict[str, Any]:
    settings = _settings(request)
    paths = request.app.state.paths

    def compute() -> tuple[str, list[Any]]:
        configured = settings.transcription.model
        if configured != "auto":
            default = configured
        else:
            rec = recommend(get_hardware(), settings.hardware.profile)
            default = rec.transcription.model
        names = sorted({default, *DEFAULT_WHISPER_CHOICES})
        status = models.model_status(
            paths.models_dir, names, settings.transcription.diarization_model
        )
        return default, status

    default, status = await asyncio.to_thread(compute)
    return {
        "model_default": default,
        "model_choices": sorted({default, *DEFAULT_WHISPER_CHOICES}),
        "model_status": status,
        "models_dir": str(paths.models_dir),
        "download": _download_manager(request).snapshot(),
        "engine_missing": models.missing_engine_modules(),
        "terms_url": models.DIARIZATION_TERMS_URL,
        "token_url": models.HF_TOKEN_URL,
    }


@router.get("/settings/transcription/models", response_class=HTMLResponse)
async def models_panel(request: Request) -> HTMLResponse:
    ctx = await _models_context(request)
    return render(request, "settings/_models.html", ctx)


@router.post("/settings/transcription/models/download", response_class=HTMLResponse)
async def models_download(request: Request) -> HTMLResponse:
    form = await _form(request)
    settings = _settings(request)
    whisper = (form.get("whisper") or "").strip()
    if not re.fullmatch(MODEL_NAME_PATTERN, whisper):
        raise MM3Error("E_BODY_INVALID", "Choose a Whisper model.", "", status_code=422)
    plan, setup = build_plan(
        settings,
        request.app.state.paths.models_dir,
        whisper=whisper,
        align_language=(form.get("align_language") or "").strip()[:3],
        diarization=bool(form.get("diarization")),
    )
    if not _download_manager(request).start(plan, setup=setup):
        raise MM3Error("E_DOWNLOAD_RUNNING", "A download is already running.", "Wait for it.", 409)
    return render(request, "settings/_models.html", await _models_context(request))


@router.post("/settings/transcription/hf-test", response_class=HTMLResponse)
async def hf_test(request: Request) -> HTMLResponse:
    settings = _settings(request)
    token = models.hf_token(settings)
    result = await asyncio.to_thread(
        hf_check.check_token,
        token,
        settings.transcription.diarization_model,
        offline=settings.transcription.offline,
    )
    return render(
        request,
        "settings/_result.html",
        {"ok": result.ok, "message": result.message, "hint": result.hint, "user": result.user},
    )


# -- language-model backends -------------------------------------------------------------------


async def _llm_context(request: Request) -> dict[str, Any]:
    settings = _settings(request)
    registry = _registry(request)
    backends = []
    for name in registry.names():
        try:
            info = registry.describe(name)
        except MM3Error as exc:
            info = {
                "name": name,
                "kind": registry.config(name).kind,
                "error": exc.message,
                "badge": "unavailable",
                "is_default": name == registry.default_name,
            }
        backends.append(info)
    rec = await asyncio.to_thread(recommendations.build, settings.hardware.profile)
    return {
        "backends": backends,
        "default_choices": sorted({*registry.names(), "ollama"}),
        "default_name": registry.default_name,
        "recommendations": rec,
        "kinds": kinds(),
    }


def _backend_form_ctx(request: Request, name: str | None, errors: Mapping[str, str] | None = None,
                      submitted: Mapping[str, str] | None = None) -> dict[str, Any]:  # fmt: skip
    registry = _registry(request)
    cfg = registry.config(name) if name else BackendConfig(kind="ollama")
    return {
        "orig_name": name or "",
        "name": name or "",
        "cfg": cfg,
        "key_set": bool(cfg.api_key and cfg.api_key.get_secret_value()),
        "kinds": kinds(),
        "errors": dict(errors or {}),
        "submitted": dict(submitted or {}),
        "is_new": name is None,
    }


@router.get("/settings/llm/new", response_class=HTMLResponse)
async def backend_new(request: Request) -> HTMLResponse:
    return render(request, "settings/_backend_form.html", _backend_form_ctx(request, None))


@router.get("/settings/llm/{name}/edit", response_class=HTMLResponse)
async def backend_edit(request: Request, name: str) -> HTMLResponse:
    return render(request, "settings/_backend_form.html", _backend_form_ctx(request, name))


def _int_or_none(text: str) -> int | None:
    text = text.strip()
    return int(text) if text else None


@router.post("/settings/llm/save", response_class=HTMLResponse)
async def backend_save(request: Request) -> HTMLResponse:
    form = await _form(request)
    settings = _settings(request)
    registry = _registry(request)
    orig = form.get("orig_name", "").strip()
    name = form.get("name", "").strip().lower()
    errors: dict[str, str] = {}
    if not BACKEND_NAME_RE.match(name):
        errors["name"] = "Use lowercase letters, digits, hyphens and underscores (max 32)."
    elif name != orig and name in registry.names():
        errors["name"] = "A backend with this name already exists."
    existing = registry.configs().get(orig) if orig else None
    key: SecretStr | None = existing.api_key if existing else None
    typed = form.get("api_key", "").strip()
    if form.get("clear_key"):
        key = None
    elif typed:
        key = SecretStr(typed)
    data: dict[str, Any] = {
        "kind": form.get("kind", ""),
        "base_url": form.get("base_url", "").strip() or None,
        "api_key": key,
        "region": form.get("region", "").strip() or None,
        "profile": form.get("profile", "").strip() or None,
        "default_model": form.get("default_model", "").strip() or None,
        "consent_remembered": bool(form.get("consent_remembered")),
        "cloud_embedding_consent": bool(form.get("cloud_embedding_consent")),
        "params": existing.params if existing else {},
        "headers": existing.headers if existing else {},
    }
    try:
        data["context_window"] = _int_or_none(form.get("context_window", ""))
    except ValueError:
        errors["context_window"] = "Enter a whole number."
    if data["kind"] not in kinds():
        errors["kind"] = "Choose a backend kind."
    cfg, cfg_errors = editing.validate_backend(data)
    errors.update({k: v for k, v in cfg_errors.items() if k not in errors})
    if errors or cfg is None:
        ctx = _backend_form_ctx(request, orig or None, errors, form)
        return render(request, "settings/_backend_form.html", ctx)
    backends = dict(settings.llm.backends)
    backends.pop(orig, None)
    backends[name] = cfg
    settings.llm.backends = backends
    if orig and orig != name and settings.llm.default_backend == orig:
        settings.llm.default_backend = name
    _persist(request)
    response = await _show(request, "llm", State(saved=True))
    response.headers["HX-Retarget"] = "#tab-body"  # the form itself was the target on errors
    response.headers["HX-Reswap"] = "innerHTML"
    return response


@router.post("/settings/llm/default", response_class=HTMLResponse)
async def backend_default(request: Request) -> HTMLResponse:
    form = await _form(request)
    name = form.get("default_backend", "")
    # "ollama" is always allowed: with no explicit entry it means the local server.
    if name not in {*_registry(request).names(), "ollama"}:
        raise MM3Error("E_BODY_INVALID", "Choose one of the configured backends.", "", 422)
    _settings(request).llm.default_backend = name
    _persist(request)
    return await _show(request, "llm", State(saved=True))


@router.post("/settings/llm/{name}/delete", response_class=HTMLResponse)
async def backend_delete(request: Request, name: str) -> HTMLResponse:
    settings = _settings(request)
    if name == _registry(request).default_name:
        raise MM3Error(
            "E_LLM_CONFIG",
            "This is the default backend.",
            "Choose another default first, then remove it.",
            status_code=409,
        )
    if name not in settings.llm.backends:
        raise MM3Error("E_LLM_UNKNOWN_BACKEND", f"No backend named '{name}'.", "", 404)
    backends = dict(settings.llm.backends)
    del backends[name]
    settings.llm.backends = backends
    _persist(request)
    return await _show(request, "llm", State(saved=True))


@router.post("/settings/llm/{name}/revoke-consent", response_class=HTMLResponse)
async def backend_revoke(request: Request, name: str) -> HTMLResponse:
    settings = _settings(request)
    cfg = settings.llm.backends.get(name)
    if cfg is None:
        raise MM3Error("E_LLM_UNKNOWN_BACKEND", f"No backend named '{name}'.", "", 404)
    cfg.consent_remembered = False
    cfg.cloud_embedding_consent = False
    _persist(request)
    return await _show(request, "llm", State(saved=True))


@router.post("/settings/llm/{name}/test", response_class=HTMLResponse)
async def backend_test(request: Request, name: str) -> HTMLResponse:
    status = await _registry(request).get(name).test_connection()
    return render(
        request,
        "settings/_result.html",
        {"ok": status.ok, "message": status.message, "hint": status.hint, "user": None},
    )


@router.get("/settings/llm/models", response_class=HTMLResponse)
async def backend_models_for_form(
    request: Request,
    target: str,
    backend: str = "",
    show_all: bool = False,
    minutes: float | None = None,
    template: str | None = None,
) -> HTMLResponse:
    """The same drop-down for a form that has its own backend select (the review page)."""
    name = backend or _registry(request).default_name
    return await backend_models(request, name, target, show_all, minutes, template)


@router.get("/settings/llm/{name}/models", response_class=HTMLResponse)
async def backend_models(
    request: Request,
    name: str,
    target: str = "b-model",
    show_all: bool = False,
    minutes: float | None = None,
    template: str | None = None,
) -> HTMLResponse:
    """The model drop-down for the input ``target`` (Settings and New meeting). It lists the
    capable models of the backend, the same set the JSON API reports."""
    picker: dict[str, Any] | None = None
    try:
        picker = await picker_for(request, name, minutes, template)
        error = ""
    except MM3Error as exc:
        error = exc.message
    default = _registry(request).config(name).default_model
    return render(
        request,
        "settings/_model_picker.html",
        {
            "p": picker,
            "error": error,
            "default_model": default or "",
            "show_all": show_all,
            "backend_name": name,
            "minutes": minutes,
            "template": template,
            "target": target if re.fullmatch(r"[a-z0-9-]+", target) else "b-model",
        },
    )


# -- privacy: retention preview and voiceprints ------------------------------------------------


def _privacy_context(request: Request) -> dict[str, Any]:
    settings = _settings(request)
    runner = getattr(request.app.state, "runner", None)
    preview: list[dict[str, object]] = []
    if runner is not None and runner.started:
        preview = [item.to_dict() for item in runner.prune(dry_run=True)]
    people: list[dict[str, Any]] = []
    db = getattr(request.app.state, "db", None)
    if db is not None:
        people = [p.to_dict() for p in VoiceprintStore(db, enabled=True).list_people()]
    return {
        "prune_preview": preview,
        "prune_bytes": sum(int(str(p["bytes"])) for p in preview),
        "people": people,
        "voiceprints_on": settings.privacy.voiceprints_enabled,
        "host": settings.server.host,
        "loopback": settings.is_loopback,
        "confirm_token": None,
    }


@router.post("/settings/privacy/prune", response_class=HTMLResponse)
async def prune_now(request: Request) -> HTMLResponse:
    runner = getattr(request.app.state, "runner", None)
    if runner is None or not runner.started:
        raise MM3Error("E_RUNNER_DOWN", "The job runner is not running.", "", status_code=503)
    items = await asyncio.to_thread(runner.prune)
    state = State(saved=True, notices=[f"Deleted the audio of {len(items)} meeting(s)."])
    return await _show(request, "privacy", state)


@router.post("/settings/privacy/voiceprints/{person_id}/delete", response_class=HTMLResponse)
async def voiceprint_delete(request: Request, person_id: str) -> HTMLResponse:
    person = _store(request).delete_person(person_id)
    state = State(saved=True, notices=[f"Deleted the voiceprint of {person.display_name}."])
    return await _show(request, "privacy", state)


@router.post("/settings/privacy/voiceprints/wipe", response_class=HTMLResponse)
async def voiceprint_wipe_ask(request: Request) -> HTMLResponse:
    """Step 1 of wiping every voiceprint: show the confirmation with a single-use token."""
    store = _store(request)
    ctx = await _tab_context(request, "privacy", State())
    ctx["confirm_token"] = _wipe_tokens(request).issue(time.monotonic())
    ctx["wipe_count"] = store.count_rows()["voiceprints"]
    return _tab_response(request, "privacy", ctx, full=False)


@router.post("/settings/privacy/voiceprints/wipe/confirm", response_class=HTMLResponse)
async def voiceprint_wipe_confirm(request: Request) -> HTMLResponse:
    form = await _form(request)
    store = _store(request)
    if not _wipe_tokens(request).consume(form.get("confirm_token"), time.monotonic()):
        raise MM3Error(
            "E_CONFIRM_REQUIRED",
            "The confirmation expired.",
            "Press “Delete all voiceprints” again.",
            status_code=428,
        )
    deleted = store.wipe(get_runner(request).jobs_root)
    state = State(
        saved=True, notices=[f"Deleted all voiceprints ({deleted.get('voiceprints', 0)})."]
    )
    return await _show(request, "privacy", state)


@router.post("/settings/privacy/voiceprints/wipe/cancel", response_class=HTMLResponse)
async def voiceprint_wipe_cancel(request: Request) -> HTMLResponse:
    return await _show(request, "privacy")


# -- about -------------------------------------------------------------------------------------


async def _about_context(request: Request) -> dict[str, Any]:
    settings = _settings(request)
    paths = request.app.state.paths
    checks = await asyncio.to_thread(run_checks, settings, paths)
    where = [
        ("Config file", paths.config_file),
        ("Config folder", paths.config_dir),
        ("Data folder", paths.data_dir),
        ("Model cache", paths.models_dir),
        ("Database", paths.database),
        ("Logs", paths.logs_dir),
    ]
    return {
        "checks": checks,
        "version": __version__,
        "locations": [(label, str(p)) for label, p in where],
        "can_open": _can_open_folders(),
    }


@router.post("/settings/about/open", response_class=HTMLResponse)
async def open_folder(request: Request) -> HTMLResponse:
    """Reveal the config folder in the file manager (native installs only)."""
    if not _can_open_folders():
        raise MM3Error(
            "E_NOT_SUPPORTED",
            "Opening folders is not available here.",
            "Copy the path and open it yourself.",
            status_code=409,
        )
    folder = request.app.state.paths.config_dir
    subprocess.Popen(["xdg-open", str(folder)])  # noqa: S603, S607 - fixed program, our own path
    return HTMLResponse('<span class="ok">Opened.</span>')
