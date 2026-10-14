"""The "Update older notes" card on the Meetings page (Phase 15a, R25; ``review/upgrade.py``).

The card shows what would change (a dry run that writes nothing), the model that will be used
and a time estimate. The user can preview one note's new sections, then run the update in the
background with progress and cancel, and gets a per-note result list with links.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from meetingmaster3.config.settings import Settings
from meetingmaster3.errors import MM3Error
from meetingmaster3.jobs.pipeline import fake_pipeline_enabled
from meetingmaster3.markdown.sections import render_section
from meetingmaster3.review.upgrade import (
    ModelChoice,
    UpgradePlan,
    UpgradeRun,
    choose_model,
    estimate_note_seconds,
    generate_sections,
    plan_note,
    plan_vault,
)
from meetingmaster3.templates.loader import MANIFEST_NAME, TemplateLibrary, planning_library
from meetingmaster3.vault.io import read_text
from meetingmaster3.vault.paths import confine, resolve_vault_root
from meetingmaster3.web.pages import render
from meetingmaster3.web.render import render_markdown

router = APIRouter()

RUN_KEY = "notes_upgrade_run"


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def _run(request: Request) -> UpgradeRun | None:
    run: UpgradeRun | None = getattr(request.app.state, RUN_KEY, None)
    return run


def _root(settings: Settings) -> Path | None:
    if settings.vault.path is None:
        return None
    try:
        return resolve_vault_root(settings.vault.path)
    except MM3Error:
        return None


async def _model(request: Request) -> ModelChoice:
    """The default backend and model; the offline fake model when the server runs with
    ``MM3_FAKE_PIPELINE=1`` (like the review workspace)."""
    settings = _settings(request)
    if fake_pipeline_enabled():
        from meetingmaster3.jobs.fakes import fake_backend

        name, backend = fake_backend(settings, None)
        cfg = settings.llm.backends.get(name)
        cloud = not backend.is_local and not (cfg is not None and cfg.consent_remembered)
        return ModelChoice(name, "fake-model", backend, cloud)
    return await choose_model(request.app.state.llm_registry, settings, None, None)


async def _choice(request: Request) -> tuple[ModelChoice | None, str]:
    try:
        return await _model(request), ""
    except MM3Error as exc:
        return None, f"{exc.message} {exc.hint}".strip()


def _library(request: Request, root: Path) -> TemplateLibrary:
    settings = _settings(request)
    manifest = request.app.state.paths.data_dir / MANIFEST_NAME
    return planning_library(root, settings.vault.templates_subfolder, manifest)


def _minutes(seconds: int) -> str:
    if seconds < 90:
        return "about a minute"
    return f"about {round(seconds / 60)} minutes"


def _link(rel: str) -> str:
    return f"/open/note?path={quote(rel, safe='')}"


async def _card_context(request: Request) -> dict[str, Any]:
    settings = _settings(request)
    run = _run(request)
    root = _root(settings)
    if root is None:
        return {"hidden": True}
    library = await asyncio.to_thread(_library, request, root)
    plan: UpgradePlan = await asyncio.to_thread(plan_vault, root, library, settings)
    choice, problem = (None, "")
    if any(n.needs_model for n in plan.todo):
        choice, problem = await _choice(request)
    return {
        "hidden": not plan.todo and run is None,
        "plan": plan,
        "counts": plan.counts(),
        "notes": [
            {**n.to_dict(), "link": _link(n.rel), "seconds": estimate_note_seconds(n)}
            for n in plan.todo
        ],
        "skipped": plan.skipped,
        "choice": choice,
        "problem": problem,
        "estimate": _minutes(plan.estimate_seconds()),
        "run": _run_context(run),
    }


def _run_context(run: UpgradeRun | None) -> dict[str, Any] | None:
    if run is None:
        return None
    return {
        "status": run.status,
        "total": run.total,
        "done": run.done_count,
        "current": run.current,
        "error": run.error,
        "model": f"{run.choice.backend_name} · {run.choice.model}" if run.choice else "",
        "results": [{**r.to_dict(), "link": _link(r.rel)} for r in run.results],
        "running": run.status == "running",
        "percent": round(100 * run.done_count / run.total) if run.total else 100,
    }


@router.get("/ui/notes/upgrade", response_class=HTMLResponse)
async def upgrade_card(request: Request) -> HTMLResponse:
    return render(request, "partials/upgrade.html", await _card_context(request))


@router.get("/ui/notes/upgrade/status", response_class=HTMLResponse)
async def upgrade_status(request: Request) -> HTMLResponse:
    return render(request, "partials/upgrade_run.html", {"run": _run_context(_run(request))})


@router.post("/ui/notes/upgrade/preview", response_class=HTMLResponse)
async def upgrade_preview(
    request: Request, path: str = Form(...), cloud_consent: str = Form("")
) -> HTMLResponse:
    """Generate one note's new sections and show them; nothing is written."""
    settings = _settings(request)
    root = _root(settings)
    if root is None:
        raise MM3Error("E_VAULT_NOT_SET", "No vault is set.", "Choose your vault in Settings.")
    note = confine(root, path)
    library = await asyncio.to_thread(_library, request, root)
    text = read_text(note)
    plan = plan_note(root, note, library, settings, text)
    context: dict[str, Any] = {"plan": plan, "link": _link(plan.rel), "sections": []}
    if plan.needs_model:
        choice = await _model(request)
        warnings: list[str] = []
        sections = await generate_sections(
            plan,
            text,
            library=library,
            settings=settings,
            backend=choice.backend,
            backend_name=choice.backend_name,
            model=choice.model,
            cloud_consent=bool(cloud_consent),
            warn=warnings.append,
        )
        context["sections"] = [
            {"title": s.title, "html": render_markdown(render_section(s))}
            for s in sections.values()
        ]
        context["warnings"] = warnings
        context["model"] = f"{choice.backend_name} · {choice.model}"
    return render(request, "partials/upgrade_preview.html", context)


@router.post("/ui/notes/upgrade/start", response_class=HTMLResponse)
async def upgrade_start(request: Request, cloud_consent: str = Form("")) -> HTMLResponse:
    current = _run(request)
    if current is not None and current.status == "running":
        return render(request, "partials/upgrade_run.html", {"run": _run_context(current)})
    settings = _settings(request)
    root = _root(settings)
    if root is None:
        raise MM3Error("E_VAULT_NOT_SET", "No vault is set.", "Choose your vault in Settings.")
    library = await asyncio.to_thread(_library, request, root)
    plan = await asyncio.to_thread(plan_vault, root, library, settings)
    choice = None
    if any(n.needs_model for n in plan.todo):
        choice = await _model(request)
        if choice.cloud and not cloud_consent:
            raise MM3Error(
                "E_CONSENT_REQUIRED",
                f"Updating these notes sends their transcripts to {choice.backend_name}, a "
                "cloud service.",
                "Tick the consent box, or choose a local model as the default in Settings.",
                status_code=409,
            )
    run = UpgradeRun(plan=plan, choice=choice)
    run.task = asyncio.create_task(
        run.run(root, library=library, settings=settings, cloud_consent=bool(cloud_consent))
    )
    setattr(request.app.state, RUN_KEY, run)
    return render(request, "partials/upgrade_run.html", {"run": _run_context(run)})


@router.post("/ui/notes/upgrade/cancel", response_class=HTMLResponse)
async def upgrade_cancel(request: Request) -> HTMLResponse:
    run = _run(request)
    if run is not None:
        run.cancel()
    return render(request, "partials/upgrade_run.html", {"run": _run_context(run)})
