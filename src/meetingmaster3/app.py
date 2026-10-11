"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from meetingmaster3 import __version__
from meetingmaster3.config.settings import Settings, load_settings
from meetingmaster3.errors import install_error_handlers
from meetingmaster3.web.hardware import router as hardware_router
from meetingmaster3.web.routes import WEB_DIR, router
from meetingmaster3.web.security import CSRFMiddleware, SecurityHeadersMiddleware


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    app = FastAPI(
        title="MeetingMaster3", version=__version__, docs_url=None, redoc_url=None, openapi_url=None
    )
    app.state.settings = settings
    install_error_handlers(app)
    app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
    app.include_router(router)
    app.include_router(hardware_router)

    # Added innermost-first: TrustedHost runs first, then headers, then CSRF.
    app.add_middleware(CSRFMiddleware, trusted_hosts=settings.trusted_hosts)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
    return app
