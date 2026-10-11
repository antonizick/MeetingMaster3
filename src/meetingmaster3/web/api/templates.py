"""Templates and generation API: list/install templates, (re)generate a job's notes, and preview
the regeneration of one section of a vault note.

State-changing routes are POST and therefore pass the CSRF middleware (S2).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from meetingmaster3.config.settings import Settings
from meetingmaster3.errors import MM3Error
from meetingmaster3.jobs.models import RESUMABLE, JobStatus
from meetingmaster3.llm.consent import requires_consent
from meetingmaster3.llm.registry import BackendRegistry
from meetingmaster3.templates.loader import MANIFEST_NAME, install_builtins
from meetingmaster3.templates.regenerate import preview_regeneration
from meetingmaster3.templates.stages import template_library
from meetingmaster3.vault.paths import resolve_vault_root
from meetingmaster3.web.api.jobs import get_runner

router = APIRouter()


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def _registry(request: Request) -> BackendRegistry:
    registry: BackendRegistry = request.app.state.llm_registry
    return registry


async def _body[M: BaseModel](request: Request, model: type[M]) -> M:
    try:
        data = await request.json() if await request.body() else {}
    except ValueError as exc:
        raise MM3Error("E_BODY_INVALID", "The request body is not valid JSON.", "") from exc
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first.get("loc", ())) or "body"
        raise MM3Error(
            "E_BODY_INVALID",
            f"Invalid field {where!r}: {first.get('msg', 'invalid value')}.",
            "Check the field names and values.",
            status_code=422,
        ) from exc


@router.get("/api/templates")
async def list_templates(request: Request) -> dict[str, Any]:
    settings = _settings(request)
    library = template_library(settings, request.app.state.paths.data_dir)
    return {
        "default": settings.generation.default_template,
        "templates": [e.to_dict() for e in library.listing()],
    }


@router.post("/api/templates/install")
async def install_templates(request: Request) -> dict[str, Any]:
    """Copy the built-in templates into the vault (never replacing the user's edits)."""
    settings = _settings(request)
    root = resolve_vault_root(settings.vault.path)
    results = install_builtins(
        root,
        settings.vault.templates_subfolder,
        request.app.state.paths.data_dir / MANIFEST_NAME,
    )
    return {"folder": settings.vault.templates_subfolder, "results": [r.to_dict() for r in results]}


class GenerateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template: str | None = None
    backend: str | None = None
    model: str | None = None
    cloud_consent: bool | None = None
    instructions: str | None = Field(default=None, max_length=4000)


@router.post("/api/jobs/{job_id}/generate")
async def generate_notes(request: Request, job_id: str) -> dict[str, Any]:
    """Choose the template, backend or model for a job's notes and (re)run generation.

    * A queued job, or one waiting for input before ``generate``: the options are stored and
      apply when generation runs.
    * A job waiting for cloud consent in ``generate``: the options are stored and, if they make
      consent unnecessary (a local backend) or give it, generation continues.
    * A failed, cancelled or interrupted job: it resumes from ``generate`` with the new options
      (even if the notes were drafted already).
    """
    runner = get_runner(request)
    body = await _body(request, GenerateBody)
    overrides = body.model_dump(exclude_none=True)
    job = runner.get(job_id)
    if job.status in RESUMABLE:
        runner.resume(job_id, overrides, from_stage="generate")
    elif job.status in {JobStatus.QUEUED, JobStatus.WAITING_FOR_INPUT}:
        job = runner.update_options(job_id, overrides)
        if job.status is JobStatus.WAITING_FOR_INPUT and runner.waiting_stage(job_id) == "generate":
            name = job.settings.get("backend") or _settings(request).llm.default_backend
            local = not requires_consent(_registry(request).get(name))
            if local or body.cloud_consent:
                runner.submit_input(job_id, {"consent": True})
    else:
        raise MM3Error(
            "E_JOB_STATE",
            f"Notes cannot be generated for a {job.status.value} job.",
            "A running job will generate its notes itself; a written note can be regenerated "
            "section by section (POST /api/notes/regenerate-section).",
            status_code=409,
        )
    return runner.describe(job_id)


class RegenerateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str = Field(min_length=1, max_length=4096)
    """The note's path relative to the vault root."""
    section_id: str = Field(min_length=1, max_length=64)
    instructions: str | None = Field(default=None, max_length=4000)
    backend: str | None = None
    model: str | None = None
    cloud_consent: bool = False


@router.post("/api/notes/regenerate-section")
async def regenerate_note_section(request: Request) -> dict[str, Any]:
    """Regenerate one section and return the old and new bodies with diffs. Nothing is
    written: the client applies the change (and archives the old version) separately."""
    body = await _body(request, RegenerateBody)
    settings = _settings(request)
    preview = await preview_regeneration(
        settings,
        template_library(settings, request.app.state.paths.data_dir),
        _registry(request).get,
        note=body.note,
        section_id=body.section_id,
        instructions=body.instructions,
        backend=body.backend,
        model=body.model,
        cloud_consent=body.cloud_consent,
    )
    return preview.to_dict()
