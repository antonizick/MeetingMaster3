"""User-facing errors: a stable code, a message and a remediation hint."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from markupsafe import escape

if TYPE_CHECKING:  # pure modules (domain, markdown, vault) import MM3Error without FastAPI
    from fastapi import FastAPI, Request
    from fastapi.responses import Response


class MM3Error(Exception):
    """An error that is safe to show to the user."""

    status_code = 400

    def __init__(
        self,
        code: str,
        message: str,
        hint: str = "",
        status_code: int | None = None,
        *,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint
        self.details = details or {}
        """Machine-readable extras for the UI, e.g. ``{"suggested_overrides": {...}}``."""
        if status_code is not None:
            self.status_code = status_code

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"code": self.code, "message": self.message, "hint": self.hint}
        if self.details:
            out["details"] = self.details
        return out


def _wants_html(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "text/html" in accept and "application/json" not in accept


async def mm3_error_handler(request: Request, exc: Exception) -> Response:
    from fastapi.responses import HTMLResponse, JSONResponse

    if not isinstance(exc, MM3Error):
        raise exc
    if request.headers.get("hx-request"):  # an HTMX action: a fragment for the toast region
        fragment = (
            f'<div class="toast error" role="alert"><strong>{escape(exc.message)}</strong>'
            f" <span>{escape(exc.hint)}</span> <small>({escape(exc.code)})</small></div>"
        )
        return HTMLResponse(fragment, status_code=exc.status_code)
    if _wants_html(request):
        from meetingmaster3.web.pages import render  # lazy: this module must not need FastAPI

        return render(request, "error.html", {"error": exc}, status_code=exc.status_code)
    return JSONResponse(exc.to_dict(), status_code=exc.status_code)


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(MM3Error, mm3_error_handler)
