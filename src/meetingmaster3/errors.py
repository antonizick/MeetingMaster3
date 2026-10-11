"""User-facing errors: a stable code, a message and a remediation hint."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from markupsafe import escape


class MM3Error(Exception):
    """An error that is safe to show to the user."""

    status_code = 400

    def __init__(self, code: str, message: str, hint: str = "", status_code: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint
        if status_code is not None:
            self.status_code = status_code

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message, "hint": self.hint}


def _wants_html(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "text/html" in accept and "application/json" not in accept


async def mm3_error_handler(request: Request, exc: Exception) -> Response:
    if not isinstance(exc, MM3Error):
        raise exc
    if _wants_html(request):
        body = (
            f"<!doctype html><title>Error</title><h1>{escape(exc.code)}</h1>"
            f"<p>{escape(exc.message)}</p><p>{escape(exc.hint)}</p>"
        )
        return HTMLResponse(body, status_code=exc.status_code)
    return JSONResponse(exc.to_dict(), status_code=exc.status_code)


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(MM3Error, mm3_error_handler)
