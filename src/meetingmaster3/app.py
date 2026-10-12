"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from meetingmaster3 import __version__
from meetingmaster3.config.paths import AppPaths, resolve_paths
from meetingmaster3.config.settings import Settings, load_settings
from meetingmaster3.errors import MM3Error, install_error_handlers
from meetingmaster3.llm.registry import BackendRegistry
from meetingmaster3.web.api.export import router as export_router
from meetingmaster3.web.api.feedback import router as feedback_router
from meetingmaster3.web.api.jobs import router as jobs_router
from meetingmaster3.web.api.speakers import speakers_router, voiceprints_router
from meetingmaster3.web.api.templates import router as templates_router
from meetingmaster3.web.feedback_ui import router as feedback_ui_router
from meetingmaster3.web.hardware import router as hardware_router
from meetingmaster3.web.llm import router as llm_router
from meetingmaster3.web.pages import WEB_DIR, router
from meetingmaster3.web.review import router as review_router
from meetingmaster3.web.security import CSRFMiddleware, SecurityHeadersMiddleware
from meetingmaster3.web.settings_ui import router as settings_router
from meetingmaster3.web.templates_ui import router as templates_ui_router
from meetingmaster3.web.upgrade_ui import router as upgrade_ui_router

log = logging.getLogger(__name__)


def _install_templates(settings: Settings, paths: AppPaths) -> None:
    """First run with a vault: copy the starter templates into it (never over user edits)."""
    if settings.vault.path is None or not settings.generation.install_templates:
        return
    from meetingmaster3.templates.loader import MANIFEST_NAME, ensure_installed
    from meetingmaster3.vault.paths import resolve_vault_root

    try:
        root = resolve_vault_root(settings.vault.path)
        ensure_installed(root, settings.vault.templates_subfolder, paths.data_dir / MANIFEST_NAME)
    except (MM3Error, OSError) as exc:
        log.warning("Starter templates were not installed: %s", exc)


def create_app(settings: Settings | None = None, paths: AppPaths | None = None) -> FastAPI:
    settings = settings or load_settings()
    app_paths = paths or resolve_paths()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        from meetingmaster3.jobs.runner import JobRunner
        from meetingmaster3.storage.db import Database

        app_paths.ensure()
        _install_templates(settings, app_paths)
        db = Database.open(app_paths.database)
        runner = JobRunner(db, settings, app_paths)
        await runner.start()
        app.state.db, app.state.runner = db, runner
        try:
            yield
        finally:
            await runner.stop()
            db.close()

    app = FastAPI(
        title="MeetingMaster3",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.paths = app_paths
    app.state.llm_registry = BackendRegistry(settings)
    install_error_handlers(app)
    app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
    app.include_router(router)
    app.include_router(review_router)
    app.include_router(hardware_router)
    app.include_router(llm_router)
    app.include_router(jobs_router)
    app.include_router(speakers_router)
    app.include_router(voiceprints_router)
    app.include_router(templates_router)
    app.include_router(feedback_router)
    app.include_router(export_router)
    app.include_router(feedback_ui_router)
    app.include_router(settings_router)
    app.include_router(templates_ui_router)
    app.include_router(upgrade_ui_router)

    # Added innermost-first: TrustedHost runs first, then headers, then CSRF.
    app.add_middleware(CSRFMiddleware, trusted_hosts=settings.trusted_hosts)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
    return app
